import * as XLSX from 'xlsx';
import * as path from 'path';
import * as fs from 'fs';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const INPUT_FILE = path.resolve(__dirname, '../../../hdfc_daily_payout_2026-02-13T09_58_04.558625095Z.xlsx');
const OUTPUT_FILE = path.resolve(__dirname, '../../../TPV_Projections_UAE_UK.xlsx');
const PROJECTION_MONTHS = 6;

// Regional split derived from BRS Audit bank-currency volumes:
// GBP corridors (HDFC GBP + YBL GBP) ≈ 72% of total book value
// USD corridors (HDFC USD + YBL USD) ≈ 28% of total book value
// Adjust these if you have more precise regional breakdowns.
const REGION_SPLITS: Record<string, number> = {
  UAE: 0.28,
  UK: 0.72,
};

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

  // XLSX numeric serial date
  if (typeof raw === 'number') {
    const d = XLSX.SSF.parse_date_code(raw);
    return new Date(d.y, d.m - 1, d.d);
  }

  // String: "July 4, 2025, 12:00 AM"
  const str = String(raw).replace(/, 12:00 AM/, '').trim();
  const d = new Date(str);
  return isNaN(d.getTime()) ? null : d;
}

function monthKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function monthLabel(key: string): string {
  const [y, m] = key.split('-');
  const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${names[parseInt(m, 10) - 1]} ${y}`;
}

// Simple linear regression: y = slope * x + intercept
function linearRegression(points: { x: number; y: number }[]): { slope: number; intercept: number; r2: number } {
  const n = points.length;
  if (n === 0) return { slope: 0, intercept: 0, r2: 0 };

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0;
  for (const p of points) {
    sumX += p.x;
    sumY += p.y;
    sumXY += p.x * p.y;
    sumX2 += p.x * p.x;
    sumY2 += p.y * p.y;
  }

  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 };

  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;

  // R² (coefficient of determination)
  const yMean = sumY / n;
  let ssTot = 0, ssRes = 0;
  for (const p of points) {
    ssTot += (p.y - yMean) ** 2;
    ssRes += (p.y - (slope * p.x + intercept)) ** 2;
  }
  const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;

  return { slope, intercept, r2 };
}

function addMonths(key: string, n: number): string {
  const [y, m] = key.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return monthKey(d);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  // 1. Read input
  if (!fs.existsSync(INPUT_FILE)) {
    console.error(`Input file not found: ${INPUT_FILE}`);
    process.exit(1);
  }

  const wb = XLSX.readFile(INPUT_FILE);
  const ws = wb.Sheets[wb.SheetNames[0]];
  const rows: any[] = XLSX.utils.sheet_to_json(ws, { defval: '' });

  console.log(`Read ${rows.length} daily records from input.`);

  // 2. Parse and aggregate monthly
  const monthly = new Map<string, number>();

  for (const row of rows) {
    const dateRaw = row['day'] ?? row['Day'] ?? row[Object.keys(row)[0]];
    const amountRaw = row['total_transfer_amount'] ?? row['Total Transfer Amount'] ?? row[Object.keys(row)[1]];

    const date = parseDate(dateRaw);
    if (!date) continue;

    const amount = parseAmount(amountRaw);
    if (amount <= 0) continue;

    const key = monthKey(date);
    monthly.set(key, (monthly.get(key) || 0) + amount);
  }

  const sortedKeys = [...monthly.keys()].sort();
  console.log(`Aggregated into ${sortedKeys.length} months: ${sortedKeys[0]} to ${sortedKeys[sortedKeys.length - 1]}`);

  // 3. Linear regression on total monthly TPV
  const points = sortedKeys.map((key, i) => ({ x: i, y: monthly.get(key)! }));
  const totalReg = linearRegression(points);
  console.log(`Total TPV trend — slope: ${(totalReg.slope / 1e6).toFixed(2)}M/month, R²: ${totalReg.r2.toFixed(4)}`);

  // 4. Project 6 months forward
  const lastKey = sortedKeys[sortedKeys.length - 1];
  const baseIndex = sortedKeys.length;

  const projectedKeys: string[] = [];
  const projectedTotal: number[] = [];
  for (let i = 0; i < PROJECTION_MONTHS; i++) {
    const key = addMonths(lastKey, i + 1);
    const value = Math.max(0, totalReg.slope * (baseIndex + i) + totalReg.intercept);
    projectedKeys.push(key);
    projectedTotal.push(value);
  }

  // 5. Build regional splits
  const regions = Object.keys(REGION_SPLITS);

  // Per-region regression for historical
  const regionHistorical: Record<string, number[]> = {};
  const regionProjected: Record<string, number[]> = {};
  const regionRegression: Record<string, { slope: number; intercept: number; r2: number }> = {};

  for (const region of regions) {
    const split = REGION_SPLITS[region];
    const hist = sortedKeys.map((k) => monthly.get(k)! * split);
    regionHistorical[region] = hist;

    const rPoints = hist.map((y, i) => ({ x: i, y }));
    const reg = linearRegression(rPoints);
    regionRegression[region] = reg;

    const proj: number[] = [];
    for (let i = 0; i < PROJECTION_MONTHS; i++) {
      proj.push(Math.max(0, reg.slope * (baseIndex + i) + reg.intercept));
    }
    regionProjected[region] = proj;
  }

  // 6. Build output workbook
  const outWb = XLSX.utils.book_new();

  // --- Summary sheet ---
  const summaryData: any[] = [];
  // Historical
  for (let i = 0; i < sortedKeys.length; i++) {
    const row: any = {
      Month: monthLabel(sortedKeys[i]),
      'Month Key': sortedKeys[i],
      Type: 'Historical',
      'Total TPV': Math.round(monthly.get(sortedKeys[i])!),
    };
    for (const region of regions) {
      row[`${region} TPV`] = Math.round(regionHistorical[region][i]);
    }
    summaryData.push(row);
  }
  // Projected
  for (let i = 0; i < PROJECTION_MONTHS; i++) {
    const row: any = {
      Month: monthLabel(projectedKeys[i]),
      'Month Key': projectedKeys[i],
      Type: 'Projected',
      'Total TPV': Math.round(projectedTotal[i]),
    };
    for (const region of regions) {
      row[`${region} TPV`] = Math.round(regionProjected[region][i]);
    }
    summaryData.push(row);
  }
  const summaryWs = XLSX.utils.json_to_sheet(summaryData);
  summaryWs['!cols'] = [
    { wch: 12 }, { wch: 10 }, { wch: 12 },
    { wch: 20 }, { wch: 20 }, { wch: 20 },
  ];
  XLSX.utils.book_append_sheet(outWb, summaryWs, 'Summary');

  // --- Per-region sheets ---
  for (const region of regions) {
    const data: any[] = [];
    for (let i = 0; i < sortedKeys.length; i++) {
      data.push({
        Month: monthLabel(sortedKeys[i]),
        'Month Key': sortedKeys[i],
        Type: 'Historical',
        'Monthly TPV': Math.round(regionHistorical[region][i]),
        'Trend Line': Math.round(regionRegression[region].slope * i + regionRegression[region].intercept),
      });
    }
    for (let i = 0; i < PROJECTION_MONTHS; i++) {
      data.push({
        Month: monthLabel(projectedKeys[i]),
        'Month Key': projectedKeys[i],
        Type: 'Projected',
        'Monthly TPV': Math.round(regionProjected[region][i]),
        'Trend Line': Math.round(regionRegression[region].slope * (baseIndex + i) + regionRegression[region].intercept),
      });
    }
    const ws = XLSX.utils.json_to_sheet(data);
    ws['!cols'] = [{ wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 20 }, { wch: 16 }];
    XLSX.utils.book_append_sheet(outWb, ws, `${region} Projection`);
  }

  // --- Regression stats sheet ---
  const statsData = [
    {
      Region: 'Total',
      'Slope (per month)': Math.round(totalReg.slope),
      'Intercept': Math.round(totalReg.intercept),
      'R²': parseFloat(totalReg.r2.toFixed(6)),
      'Split %': '100%',
    },
    ...regions.map((r) => ({
      Region: r,
      'Slope (per month)': Math.round(regionRegression[r].slope),
      'Intercept': Math.round(regionRegression[r].intercept),
      'R²': parseFloat(regionRegression[r].r2.toFixed(6)),
      'Split %': `${(REGION_SPLITS[r] * 100).toFixed(0)}%`,
    })),
  ];
  const statsWs = XLSX.utils.json_to_sheet(statsData);
  statsWs['!cols'] = [{ wch: 10 }, { wch: 20 }, { wch: 20 }, { wch: 10 }, { wch: 10 }];
  XLSX.utils.book_append_sheet(outWb, statsWs, 'Regression Stats');

  // --- Daily raw data sheet ---
  const dailyData: any[] = [];
  for (const row of rows) {
    const dateRaw = row['day'] ?? row['Day'] ?? row[Object.keys(row)[0]];
    const amountRaw = row['total_transfer_amount'] ?? row['Total Transfer Amount'] ?? row[Object.keys(row)[1]];
    const date = parseDate(dateRaw);
    if (!date) continue;
    const amount = parseAmount(amountRaw);
    if (amount <= 0) continue;
    dailyData.push({
      Date: date.toISOString().split('T')[0],
      'Total TPV': Math.round(amount),
      'UAE TPV': Math.round(amount * REGION_SPLITS.UAE),
      'UK TPV': Math.round(amount * REGION_SPLITS.UK),
    });
  }
  const dailyWs = XLSX.utils.json_to_sheet(dailyData);
  dailyWs['!cols'] = [{ wch: 12 }, { wch: 18 }, { wch: 18 }, { wch: 18 }];
  XLSX.utils.book_append_sheet(outWb, dailyWs, 'Daily Data');

  // 7. Write output
  XLSX.writeFile(outWb, OUTPUT_FILE);
  console.log(`\nOutput written to: ${OUTPUT_FILE}`);
  console.log(`\nProjections (${PROJECTION_MONTHS} months):`);
  console.log('─'.repeat(70));
  console.log(`${'Month'.padEnd(12)} ${'Total TPV'.padStart(18)} ${'UAE TPV'.padStart(18)} ${'UK TPV'.padStart(18)}`);
  console.log('─'.repeat(70));
  for (let i = 0; i < PROJECTION_MONTHS; i++) {
    const total = Math.round(projectedTotal[i]);
    const uae = Math.round(regionProjected['UAE'][i]);
    const uk = Math.round(regionProjected['UK'][i]);
    console.log(
      `${monthLabel(projectedKeys[i]).padEnd(12)} ${total.toLocaleString().padStart(18)} ${uae.toLocaleString().padStart(18)} ${uk.toLocaleString().padStart(18)}`
    );
  }
}

main();
