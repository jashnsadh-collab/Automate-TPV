import { pool } from './pool';
import fs from 'fs';
import path from 'path';

async function migrate() {
  // Schema lives in the parent of the backend directory
  const candidates = [
    path.join(__dirname, '../../..', 'schema_v1.sql'),       // from src/db/ -> New project/
    path.join(__dirname, '../../../..', 'schema_v1.sql'),     // extra level
    path.resolve(process.cwd(), '..', 'schema_v1.sql'),      // from backend/ cwd -> New project/
  ];
  let sql: string | undefined;
  for (const p of candidates) {
    if (fs.existsSync(p)) { sql = fs.readFileSync(p, 'utf-8'); break; }
  }
  if (!sql) {
    console.error('schema_v1.sql not found. Tried:', candidates);
    process.exit(1);
  }

  const client = await pool.connect();
  try {
    await client.query(sql);
    console.log('Schema applied successfully.');
  } catch (err) {
    console.error('Migration error:', err);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

migrate();
