import { pool } from './pool';
import fs from 'fs';
import path from 'path';

async function migrate() {
  const schemaPath = path.join(__dirname, '../../../..', 'schema_v1.sql');
  let sql: string;
  try {
    sql = fs.readFileSync(schemaPath, 'utf-8');
  } catch {
    // Try sibling path
    const altPath = path.join(__dirname, '../../../../schema_v1.sql');
    sql = fs.readFileSync(altPath, 'utf-8');
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
