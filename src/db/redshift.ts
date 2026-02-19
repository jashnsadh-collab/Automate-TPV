import {
  RedshiftDataClient,
  ExecuteStatementCommand,
  DescribeStatementCommand,
  GetStatementResultCommand,
  StatusString,
} from '@aws-sdk/client-redshift-data';
import type { Field, ColumnMetadata } from '@aws-sdk/client-redshift-data';
import dotenv from 'dotenv';

dotenv.config();

export const redshiftClient = new RedshiftDataClient({
  region: process.env.AWS_DEFAULT_REGION || 'ap-south-1',
});

const POLL_INTERVAL_MS = 500;
const POLL_TIMEOUT_MS = 30_000;

function extractFieldValue(field: Field): unknown {
  const f = field as any;
  if (f.isNull) return null;
  if (f.stringValue !== undefined) return f.stringValue;
  if (f.longValue !== undefined) return f.longValue;
  if (f.doubleValue !== undefined) return f.doubleValue;
  if (f.booleanValue !== undefined) return f.booleanValue;
  return null;
}

export interface RedshiftResult {
  columns: string[];
  rows: Record<string, unknown>[];
  totalRows: number;
}

export async function redshiftQuery(sql: string): Promise<RedshiftResult> {
  const workgroup = process.env.REDSHIFT_WORKGROUP;
  const database = process.env.REDSHIFT_DATABASE || 'dev';

  if (!workgroup) {
    throw new Error('REDSHIFT_WORKGROUP environment variable is not set');
  }

  // Submit the statement
  const execResult = await redshiftClient.send(
    new ExecuteStatementCommand({
      WorkgroupName: workgroup,
      Database: database,
      Sql: sql,
    })
  );

  const statementId = execResult.Id!;

  // Poll until complete
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const desc = await redshiftClient.send(
      new DescribeStatementCommand({ Id: statementId })
    );

    if (desc.Status === StatusString.FINISHED) break;

    if (
      desc.Status === StatusString.FAILED ||
      desc.Status === StatusString.ABORTED
    ) {
      throw new Error(`Redshift query failed: ${desc.Error}`);
    }

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }

  // Final status check
  const finalDesc = await redshiftClient.send(
    new DescribeStatementCommand({ Id: statementId })
  );
  if (finalDesc.Status !== StatusString.FINISHED) {
    throw new Error(`Redshift query timed out (status: ${finalDesc.Status})`);
  }

  // Fetch results
  const result = await redshiftClient.send(
    new GetStatementResultCommand({ Id: statementId })
  );

  const columns = (result.ColumnMetadata || []).map(
    (col: ColumnMetadata) => col.name || 'unknown'
  );

  const rows = (result.Records || []).map((record: Field[]) => {
    const row: Record<string, unknown> = {};
    record.forEach((field, i) => {
      row[columns[i]] = extractFieldValue(field);
    });
    return row;
  });

  return {
    columns,
    rows,
    totalRows: result.TotalNumRows ?? rows.length,
  };
}
