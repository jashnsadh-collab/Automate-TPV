import * as XLSX from 'xlsx';
import * as path from 'path';
import * as fs from 'fs';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const HOME = process.env.HOME || '/Users/apple';
const UAE_INPUT = path.join(HOME, 'Downloads/input_data_for_tpv_model__uae_2026-02-18T05_47_58.113627555Z.xlsx');
const UK_INPUT = path.join(HOME, 'Downloads/input_data_for_projections___uk_2026-02-17T05_28_09.362708878Z.xlsx');
const OUTPUT_FILE = path.resolve(__dirname, '../../../TPV_Projections_UAE_UK.xlsx');
const PROJECTION_DAYS = 180; // ~6 months

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseAmount(raw: any): number {
  if (raw == null || raw === '') return 0;
  const str = String(raw).replace(/,/g, '').replace(/[()]/g, '').trim();
  const val = parseFloat(str);
  return isNaN(val) ? 0 : val;
}

function parseDate(raw: any): Date | null {
  if (raw == null) return null;
  if (typeof raw === 'number') {
    const d = XLSX.SSF.parse_date_code(raw);
    return new Date(d.y, d.m - 1, d.d);
  }
  const str = String(raw).replace(/, 12:00 AM/, '').trim();
  const d = new Date(str);
  return isNaN(d.getTime()) ? null : d;
}

function formatDate(d: Date): string {
  return d.toISOString().split('T')[0];
}

function addDays(d: Date, n: number): Date {
  const result = new Date(d);
  result.setDate(result.getDate() + n);
  return result;
}

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function linearRegression(points: { x: number; y: number }[]): { slope: number; intercept: number; r2: number } {
  const n = points.length;
  if (n === 0) return { slope: 0, intercept: 0, r2: 0 };

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (const p of points) {
    sumX += p.x;
    sumY += p.y;
    sumXY += p.x * p.y;
    sumX2 += p.x * p.x;
  }

  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 };

  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;

  const yMean = sumY / n;
  let ssTot = 0, ssRes = 0;
  for (const p of points) {
    ssTot += (p.y - yMean) ** 2;
    ssRes += (p.y - (slope * p.x + intercept)) ** 2;
  }
  const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;

  return { slope, intercept, r2 };
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

interface DailyRecord {
  date: Date;
  totalSendAmount: number;
  transactions: number;
  users: number;
}

interface CategoryDaily {
  date: Date;
  category: string;
  totalSendAmount: number;
  transactions: number;
  users: number;
}

function loadUAE(filePath: string): { daily: Map<string, DailyRecord>; byCategory: CategoryDaily[] } {
  const wb = XLSX.readFile(filePath);
  const ws = wb.Sheets[wb.SheetNames[0]];
  const rows: any[] = XLSX.utils.sheet_to_json(ws, { defval: '' });

  const daily = new Map<string, DailyRecord>();
  const byCategory: CategoryDaily[] = [];

  for (const row of rows) {
    const date = parseDate(row['transaction_date']);
    if (!date) continue;

    const amount = parseAmount(row['total_send_amount']);
    const txns = parseAmount(row['number_of_transactions']);
    const users = parseAmount(row['transacting_users']);
    const category = String(row['user_category'] || 'Unknown');
    const key = formatDate(date);

    byCategory.push({ date, category, totalSendAmount: amount, transactions: txns, users });

    const existing = daily.get(key) || { date, totalSendAmount: 0, transactions: 0, users: 0 };
    existing.totalSendAmount += amount;
    existing.transactions += txns;
    existing.users += users;
    daily.set(key, existing);
  }

  return { daily, byCategory };
}

function loadUK(filePath: string): { daily: Map<string, DailyRecord>; byCategory: CategoryDaily[] } {
  const wb = XLSX.readFile(filePath);
  const ws = wb.Sheets[wb.SheetNames[0]];
  const rows: any[] = XLSX.utils.sheet_to_json(ws, { defval: '' });

  const daily = new Map<string, DailyRecord>();
  const byCategory: CategoryDaily[] = [];

  // UK data has time segments per category per day — aggregate to daily per category first
  const catDayMap = new Map<string, CategoryDaily>();

  for (const row of rows) {
    const date = parseDate(row['transaction_date']);
    if (!date) continue;

    const amount = parseAmount(row['total_send_amount']);
    const txns = parseAmount(row['number_of_transactions']);
    const users = parseAmount(row['transacting_users']);
    const category = String(row['user_category'] || 'Unknown');
    const key = `${formatDate(date)}|${category}`;

    const existing = catDayMap.get(key) || { date, category, totalSendAmount: 0, transactions: 0, users: 0 };
    existing.totalSendAmount += amount;
    existing.transactions += txns;
    existing.users += users;
    catDayMap.set(key, existing);
  }

  for (const entry of catDayMap.values()) {
    byCategory.push(entry);
    const key = formatDate(entry.date);
    const existing = daily.get(key) || { date: entry.date, totalSendAmount: 0, transactions: 0, users: 0 };
    existing.totalSendAmount += entry.totalSendAmount;
    existing.transactions += entry.transactions;
    existing.users += entry.users;
    daily.set(key, existing);
  }

  return { daily, byCategory };
}

// ---------------------------------------------------------------------------
// Projection
// ---------------------------------------------------------------------------

interface ProjectionResult {
  historical: { date: Date; amount: number; txns: number; users: number }[];
  projected: { date: Date; amount: number; txns: number; users: number }[];
  regression: { slope: number; intercept: number; r2: number };
  txnRegression: { slope: number; intercept: number; r2: number };
  userRegression: { slope: number; intercept: number; r2: number };
}

function projectRegion(daily: Map<string, DailyRecord>): ProjectionResult {
  const sorted = [...daily.values()].sort((a, b) => a.date.getTime() - b.date.getTime());
  const firstDate = sorted[0].date;

  const amountPoints = sorted.map((d) => ({
    x: Math.round((d.date.getTime() - firstDate.getTime()) / 86400000),
    y: d.totalSendAmount,
  }));
  const txnPoints = sorted.map((d) => ({
    x: Math.round((d.date.getTime() - firstDate.getTime()) / 86400000),
    y: d.transactions,
  }));
  const userPoints = sorted.map((d) => ({
    x: Math.round((d.date.getTime() - firstDate.getTime()) / 86400000),
    y: d.users,
  }));

  const regression = linearRegression(amountPoints);
  const txnRegression = linearRegression(txnPoints);
  const userRegression = linearRegression(userPoints);

  const lastDate = sorted[sorted.length - 1].date;
  const lastDayIdx = Math.round((lastDate.getTime() - firstDate.getTime()) / 86400000);

  const projected: { date: Date; amount: number; txns: number; users: number }[] = [];
  for (let i = 1; i <= PROJECTION_DAYS; i++) {
    const dayIdx = lastDayIdx + i;
    projected.push({
      date: addDays(lastDate, i),
      amount: Math.max(0, regression.slope * dayIdx + regression.intercept),
      txns: Math.max(0, txnRegression.slope * dayIdx + txnRegression.intercept),
      users: Math.max(0, userRegression.slope * dayIdx + userRegression.intercept),
    });
  }

  const historical = sorted.map((d) => ({
    date: d.date,
    amount: d.totalSendAmount,
    txns: d.transactions,
    users: d.users,
  }));

  return { historical, projected, regression, txnRegression, userRegression };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  for (const [label, f] of [['UAE', UAE_INPUT], ['UK', UK_INPUT]] as const) {
    if (!fs.existsSync(f)) {
      console.error(`${label} input file not found: ${f}`);
      process.exit(1);
    }
  }

  console.log('Loading UAE data...');
  const uae = loadUAE(UAE_INPUT);
  console.log(`  ${uae.daily.size} daily records, ${uae.byCategory.length} category rows`);

  console.log('Loading UK data...');
  const uk = loadUK(UK_INPUT);
  console.log(`  ${uk.daily.size} daily records, ${uk.byCategory.length} category rows`);

  console.log('\nRunning projections...');
  const uaeProj = projectRegion(uae.daily);
  const ukProj = projectRegion(uk.daily);

  console.log(`UAE — slope: ${(uaeProj.regression.slope).toFixed(2)}/day, R²: ${uaeProj.regression.r2.toFixed(4)}`);
  console.log(`UK  — slope: ${(ukProj.regression.slope).toFixed(2)}/day, R²: ${ukProj.regression.r2.toFixed(4)}`);

  // Build output workbook
  const outWb = XLSX.utils.book_new();

  // --- Combined Summary (daily) ---
  const summaryData: any[] = [];

  // Build a date-keyed map for both regions
  const allDates = new Map<string, { uaeAmt: number; ukAmt: number; type: string }>();

  for (const d of uaeProj.historical) {
    const key = formatDate(d.date);
    const entry = allDates.get(key) || { uaeAmt: 0, ukAmt: 0, type: 'Historical' };
    entry.uaeAmt = d.amount;
    allDates.set(key, entry);
  }
  for (const d of ukProj.historical) {
    const key = formatDate(d.date);
    const entry = allDates.get(key) || { uaeAmt: 0, ukAmt: 0, type: 'Historical' };
    entry.ukAmt = d.amount;
    allDates.set(key, entry);
  }
  for (const d of uaeProj.projected) {
    const key = formatDate(d.date);
    const entry = allDates.get(key) || { uaeAmt: 0, ukAmt: 0, type: 'Projected' };
    entry.type = 'Projected';
    entry.uaeAmt = d.amount;
    allDates.set(key, entry);
  }
  for (const d of ukProj.projected) {
    const key = formatDate(d.date);
    const entry = allDates.get(key) || { uaeAmt: 0, ukAmt: 0, type: 'Projected' };
    entry.type = 'Projected';
    entry.ukAmt = d.amount;
    allDates.set(key, entry);
  }

  for (const [dateStr, val] of [...allDates.entries()].sort()) {
    summaryData.push({
      Date: dateStr,
      Type: val.type,
      'UAE TPV': Math.round(val.uaeAmt),
      'UK TPV': Math.round(val.ukAmt),
      'Total TPV': Math.round(val.uaeAmt + val.ukAmt),
    });
  }

  const summaryWs = XLSX.utils.json_to_sheet(summaryData);
  summaryWs['!cols'] = [{ wch: 12 }, { wch: 12 }, { wch: 18 }, { wch: 18 }, { wch: 18 }];
  XLSX.utils.book_append_sheet(outWb, summaryWs, 'Daily Summary');

  // --- UAE Detail sheet ---
  const uaeData: any[] = [];
  for (const d of uaeProj.historical) {
    uaeData.push({
      Date: formatDate(d.date),
      Type: 'Historical',
      'Daily TPV': Math.round(d.amount),
      Transactions: Math.round(d.txns),
      Users: Math.round(d.users),
    });
  }
  for (const d of uaeProj.projected) {
    uaeData.push({
      Date: formatDate(d.date),
      Type: 'Projected',
      'Daily TPV': Math.round(d.amount),
      Transactions: Math.round(d.txns),
      Users: Math.round(d.users),
    });
  }
  const uaeWs = XLSX.utils.json_to_sheet(uaeData);
  uaeWs['!cols'] = [{ wch: 12 }, { wch: 12 }, { wch: 18 }, { wch: 14 }, { wch: 10 }];
  XLSX.utils.book_append_sheet(outWb, uaeWs, 'UAE Projection');

  // --- UK Detail sheet ---
  const ukData: any[] = [];
  for (const d of ukProj.historical) {
    ukData.push({
      Date: formatDate(d.date),
      Type: 'Historical',
      'Daily TPV': Math.round(d.amount),
      Transactions: Math.round(d.txns),
      Users: Math.round(d.users),
    });
  }
  for (const d of ukProj.projected) {
    ukData.push({
      Date: formatDate(d.date),
      Type: 'Projected',
      'Daily TPV': Math.round(d.amount),
      Transactions: Math.round(d.txns),
      Users: Math.round(d.users),
    });
  }
  const ukWs = XLSX.utils.json_to_sheet(ukData);
  ukWs['!cols'] = [{ wch: 12 }, { wch: 12 }, { wch: 18 }, { wch: 14 }, { wch: 10 }];
  XLSX.utils.book_append_sheet(outWb, ukWs, 'UK Projection');

  // --- UAE by Category sheet ---
  const uaeCatAgg = new Map<string, { date: Date; category: string; amount: number }>();
  for (const c of uae.byCategory) {
    const key = `${formatDate(c.date)}|${c.category}`;
    const existing = uaeCatAgg.get(key) || { date: c.date, category: c.category, amount: 0 };
    existing.amount += c.totalSendAmount;
    uaeCatAgg.set(key, existing);
  }
  const uaeCatData = [...uaeCatAgg.values()]
    .sort((a, b) => b.date.getTime() - a.date.getTime() || a.category.localeCompare(b.category))
    .map((d) => ({
      Date: formatDate(d.date),
      Category: d.category,
      'Daily TPV': Math.round(d.amount),
    }));
  const uaeCatWs = XLSX.utils.json_to_sheet(uaeCatData);
  uaeCatWs['!cols'] = [{ wch: 12 }, { wch: 14 }, { wch: 18 }];
  XLSX.utils.book_append_sheet(outWb, uaeCatWs, 'UAE by Category');

  // --- UK by Category sheet ---
  const ukCatData = [...uk.byCategory]
    .sort((a, b) => b.date.getTime() - a.date.getTime() || a.category.localeCompare(b.category))
    .map((d) => ({
      Date: formatDate(d.date),
      Category: d.category,
      'Daily TPV': Math.round(d.totalSendAmount),
    }));
  const ukCatWs = XLSX.utils.json_to_sheet(ukCatData);
  ukCatWs['!cols'] = [{ wch: 12 }, { wch: 14 }, { wch: 18 }];
  XLSX.utils.book_append_sheet(outWb, ukCatWs, 'UK by Category');

  // --- Monthly Summary ---
  const monthlyMap = new Map<string, { uae: number; uk: number; type: string }>();
  const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  for (const [dateStr, val] of allDates) {
    const d = new Date(dateStr);
    const mk = monthKey(d);
    const entry = monthlyMap.get(mk) || { uae: 0, uk: 0, type: val.type };
    if (val.type === 'Projected') entry.type = 'Projected';
    entry.uae += val.uaeAmt;
    entry.uk += val.ukAmt;
    monthlyMap.set(mk, entry);
  }

  const monthlyData = [...monthlyMap.entries()].sort().map(([mk, val]) => {
    const [y, m] = mk.split('-');
    return {
      Month: `${monthNames[parseInt(m, 10) - 1]} ${y}`,
      Type: val.type,
      'UAE TPV': Math.round(val.uae),
      'UK TPV': Math.round(val.uk),
      'Total TPV': Math.round(val.uae + val.uk),
    };
  });
  const monthlyWs = XLSX.utils.json_to_sheet(monthlyData);
  monthlyWs['!cols'] = [{ wch: 12 }, { wch: 12 }, { wch: 18 }, { wch: 18 }, { wch: 18 }];
  XLSX.utils.book_append_sheet(outWb, monthlyWs, 'Monthly Summary');

  // --- Regression Stats ---
  const statsData = [
    { Region: 'UAE', Metric: 'TPV', 'Slope (per day)': uaeProj.regression.slope.toFixed(2), Intercept: Math.round(uaeProj.regression.intercept), 'R²': uaeProj.regression.r2.toFixed(6) },
    { Region: 'UAE', Metric: 'Transactions', 'Slope (per day)': uaeProj.txnRegression.slope.toFixed(2), Intercept: Math.round(uaeProj.txnRegression.intercept), 'R²': uaeProj.txnRegression.r2.toFixed(6) },
    { Region: 'UAE', Metric: 'Users', 'Slope (per day)': uaeProj.userRegression.slope.toFixed(2), Intercept: Math.round(uaeProj.userRegression.intercept), 'R²': uaeProj.userRegression.r2.toFixed(6) },
    { Region: 'UK', Metric: 'TPV', 'Slope (per day)': ukProj.regression.slope.toFixed(2), Intercept: Math.round(ukProj.regression.intercept), 'R²': ukProj.regression.r2.toFixed(6) },
    { Region: 'UK', Metric: 'Transactions', 'Slope (per day)': ukProj.txnRegression.slope.toFixed(2), Intercept: Math.round(ukProj.txnRegression.intercept), 'R²': ukProj.txnRegression.r2.toFixed(6) },
    { Region: 'UK', Metric: 'Users', 'Slope (per day)': ukProj.userRegression.slope.toFixed(2), Intercept: Math.round(ukProj.userRegression.intercept), 'R²': ukProj.userRegression.r2.toFixed(6) },
  ];
  const statsWs = XLSX.utils.json_to_sheet(statsData);
  statsWs['!cols'] = [{ wch: 8 }, { wch: 14 }, { wch: 16 }, { wch: 16 }, { wch: 12 }];
  XLSX.utils.book_append_sheet(outWb, statsWs, 'Regression Stats');

  // Write output
  XLSX.writeFile(outWb, OUTPUT_FILE);
  console.log(`\nOutput written to: ${OUTPUT_FILE}`);

  // Print monthly summary
  console.log(`\nMonthly Summary (last 6 historical + ${PROJECTION_DAYS}-day projection):`);
  console.log('─'.repeat(82));
  console.log(`${'Month'.padEnd(12)} ${'Type'.padEnd(12)} ${'UAE TPV'.padStart(18)} ${'UK TPV'.padStart(18)} ${'Total TPV'.padStart(18)}`);
  console.log('─'.repeat(82));
  const lastMonths = monthlyData.slice(-12);
  for (const row of lastMonths) {
    console.log(
      `${row.Month.padEnd(12)} ${row.Type.padEnd(12)} ${row['UAE TPV'].toLocaleString().padStart(18)} ${row['UK TPV'].toLocaleString().padStart(18)} ${row['Total TPV'].toLocaleString().padStart(18)}`
    );
  }
}

main();
