import { query } from '../db/pool';

interface RuleOutcome {
  ruleCode: string;
  action: string;
  [key: string]: any;
}

interface EvaluationResult {
  matched: boolean;
  finalOutcome: RuleOutcome | null;
  evaluatedCount: number;
}

/**
 * Evaluates active policy_rule rows for a given scope against a context object.
 * Returns the first matching rule's outcome, or null if none match.
 */
export async function evaluateRules(
  companyId: string,
  scope: string,
  context: Record<string, any>,
): Promise<EvaluationResult> {
  const result = await query(
    `SELECT rule_code, expression_json, outcome_json
     FROM policy_rule
     WHERE company_id = $1 AND scope = $2 AND is_active = TRUE
       AND valid_from <= NOW()
       AND (valid_to IS NULL OR valid_to > NOW())
     ORDER BY priority ASC`,
    [companyId, scope],
  );

  for (const row of result.rows) {
    const expr = row.expression_json;
    const outcome = row.outcome_json;

    let matched = false;
    if (expr.whenAll && Array.isArray(expr.whenAll)) {
      matched = expr.whenAll.every((cond: string) => evaluateCondition(cond, context));
    } else if (expr.whenAny && Array.isArray(expr.whenAny)) {
      matched = expr.whenAny.some((cond: string) => evaluateCondition(cond, context));
    }

    if (matched) {
      return {
        matched: true,
        finalOutcome: { ruleCode: row.rule_code, ...outcome },
        evaluatedCount: result.rows.length,
      };
    }
  }

  return { matched: false, finalOutcome: null, evaluatedCount: result.rows.length };
}

function evaluateCondition(condition: string, context: Record<string, any>): boolean {
  // Parse: "fieldName operator value"
  // Supports: ==, !=, <, <=, >, >=, in
  const inMatch = condition.match(/^(\w+)\s+in\s+\[(.+)\]$/);
  if (inMatch) {
    const fieldName = inMatch[1];
    const fieldValue = context[fieldName];
    const listItems = inMatch[2].split(',').map((s) => s.trim().replace(/^['"]|['"]$/g, ''));
    return listItems.includes(String(fieldValue));
  }

  const opMatch = condition.match(/^(\w+)\s*(==|!=|<=|>=|<|>)\s*(.+)$/);
  if (!opMatch) return false;

  const fieldName = opMatch[1];
  const operator = opMatch[2];
  const rawValue = opMatch[3].trim().replace(/^['"]|['"]$/g, '');

  const fieldValue = context[fieldName];
  if (fieldValue === undefined) return false;

  // Coerce to number if both sides are numeric
  const numField = Number(fieldValue);
  const numValue = Number(rawValue);
  const useNumbers = !isNaN(numField) && !isNaN(numValue);

  const left = useNumbers ? numField : String(fieldValue);
  const right = useNumbers ? numValue : rawValue;

  // Handle boolean string comparison
  if (rawValue === 'true' || rawValue === 'false') {
    const boolValue = rawValue === 'true';
    if (operator === '==') return fieldValue === boolValue;
    if (operator === '!=') return fieldValue !== boolValue;
  }

  switch (operator) {
    case '==': return left === right;
    case '!=': return left !== right;
    case '<': return left < right;
    case '<=': return left <= right;
    case '>': return left > right;
    case '>=': return left >= right;
    default: return false;
  }
}
