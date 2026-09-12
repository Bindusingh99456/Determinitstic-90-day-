import fs from 'fs';
import path from 'path';
import { evaluateDecision } from './decisionEngine.js';
import { PurchaseRequest, FinancialEvent, PaymentOption } from './types.js';

interface RequestInput {
  request_id: string;
  product: string;
  amount: number;
  desired_date: string;
  start_balance: number;
  minimum_safety_buffer: number;
  events: FinancialEvent[];
  payment_options?: PaymentOption[];
}

const competitionRequests: RequestInput[] = [
  {
    request_id: 'R001',
    product: 'Laptop',
    amount: 60000,
    desired_date: '2026-09-30',
    start_balance: 20000,
    minimum_safety_buffer: 10000,
    events: [
      {
        event_id: 'EVT_SALARY_001',
        user_id: 'U1',
        account_id: 'ACC1',
        event_type: 'INCOME',
        status: 'CONFIRMED',
        amount: 80000,
        event_date: '2026-09-30',
        category: 'SALARY',
      },
    ],
  },
  {
    request_id: 'R002',
    product: 'Smart Watch',
    amount: 800,
    desired_date: '2026-09-12',
    start_balance: 5000,
    minimum_safety_buffer: 1000,
    events: [],
  },
  {
    request_id: 'R003',
    product: 'Television',
    amount: 1500,
    desired_date: '2026-09-12',
    start_balance: 1800,
    minimum_safety_buffer: 1000,
    events: [
      {
        event_id: 'EVT_SALARY_14D_1',
        user_id: 'U1',
        account_id: 'ACC1',
        event_type: 'INCOME',
        status: 'CONFIRMED',
        amount: 2000,
        event_date: '2026-09-25',
        category: 'SALARY',
      },
      {
        event_id: 'EVT_SALARY_14D_2',
        user_id: 'U1',
        account_id: 'ACC1',
        event_type: 'INCOME',
        status: 'CONFIRMED',
        amount: 2000,
        event_date: '2026-10-09',
        category: 'SALARY',
      },
    ],
    payment_options: [
      {
        option_id: 'OPT_TV_BNPL',
        type: 'BNPL_INSTALLMENTS',
        down_payment: 300,
        installment_amount: 300,
        num_installments: 5,
        frequency_days: 14,
      },
    ],
  },
  {
    request_id: 'R004',
    product: 'Phone',
    amount: 1000,
    desired_date: '2026-10-01',
    start_balance: 1200,
    minimum_safety_buffer: 1000,
    events: [
      {
        event_id: 'EVT_SUB',
        user_id: 'U1',
        account_id: 'ACC1',
        event_type: 'EXPENSE',
        status: 'CONFIRMED',
        amount: 200,
        event_date: '2026-09-15',
        is_recurring: true,
        category: 'SUBSCRIPTION',
        is_essential: false,
      },
      {
        event_id: 'EVT_SALARY_OCT',
        user_id: 'U1',
        account_id: 'ACC1',
        event_type: 'INCOME',
        status: 'CONFIRMED',
        amount: 800,
        event_date: '2026-10-01',
        category: 'SALARY',
      },
    ],
  },
  {
    request_id: 'R005',
    product: 'Vacation',
    amount: 50000,
    desired_date: '2026-09-12',
    start_balance: 2000,
    minimum_safety_buffer: 1000,
    events: [],
  },
];

const VALID_STATUSES = ['affordable_now', 'affordable_with_plan', 'affordable_later', 'not_affordable'];
const VALID_METHODS = ['full_payment', 'partial_payment', 'installments', 'wait', 'not_recommended'];

function validateRow(row: any, reqInput: RequestInput) {
  const errors: string[] = [];

  // 1. Missing / duplicate request ID check
  if (!row.request_id || typeof row.request_id !== 'string') {
    errors.push('Missing request_id');
  }

  // 2. Safe amount bounds
  if (typeof row.amount_safe_to_pay !== 'number' || row.amount_safe_to_pay < 0) {
    errors.push(`Invalid amount_safe_to_pay: ${row.amount_safe_to_pay}`);
  }

  // 3. Valid status
  if (!VALID_STATUSES.includes(row.affordability_status)) {
    errors.push(`Invalid affordability_status: ${row.affordability_status}`);
  }

  // 4. Valid payment method
  if (!VALID_METHODS.includes(row.recommended_payment_method)) {
    errors.push(`Invalid recommended_payment_method: ${row.recommended_payment_method}`);
  }

  // 5. Valid payment plan & chronological dates check
  if (!row.payment_plan || typeof row.payment_plan !== 'string') {
    errors.push('Missing payment_plan');
  } else if (row.payment_plan !== 'none') {
    const parts = row.payment_plan.split(',').map((p: string) => p.trim());
    let lastDate = '';
    let totalPlanAmt = 0;

    for (const part of parts) {
      const [dStr, amtStr] = part.split(':');
      if (!dStr || !amtStr) {
        errors.push(`Malformed payment_plan entry: '${part}'`);
        continue;
      }

      if (lastDate && dStr < lastDate) {
        errors.push(`Non-chronological payment plan date: ${dStr} < ${lastDate}`);
      }
      lastDate = dStr;
      totalPlanAmt += parseFloat(amtStr);
    }

    // Payment totals check
    if (Math.abs(totalPlanAmt - reqInput.amount) > 0.01) {
      errors.push(`Payment plan total ($${totalPlanAmt}) does not match full price ($${reqInput.amount})`);
    }
  }

  // 6. Chronological earliest date check
  if (!row.earliest_date_for_full_payment || !/^\d{4}-\d{2}-\d{2}$/.test(row.earliest_date_for_full_payment)) {
    errors.push(`Invalid earliest_date_for_full_payment: ${row.earliest_date_for_full_payment}`);
  }

  // 7. Spending changes validity
  if (!row.spending_changes_needed || typeof row.spending_changes_needed !== 'string') {
    errors.push('Missing spending_changes_needed');
  }

  // 8. Explanation consistency
  if (!row.decision_explanation || typeof row.decision_explanation !== 'string' || row.decision_explanation.length < 10) {
    errors.push('Inconsistent or empty decision_explanation');
  }

  if (errors.length > 0) {
    throw new Error(`Row validation failed for ${row.request_id}:\n${errors.join('\n')}`);
  }
}

export function generateCSVOutput() {
  console.log('Generating backend-evaluated competition output.csv...');

  const rows: string[] = [];
  const header = 'request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation';
  rows.push(header);

  const seenReqIds = new Set<string>();

  for (const reqInput of competitionRequests) {
    if (seenReqIds.has(reqInput.request_id)) {
      throw new Error(`Duplicate request ID detected: ${reqInput.request_id}`);
    }
    seenReqIds.add(reqInput.request_id);

    const internalReq: PurchaseRequest = {
      request_id: reqInput.request_id,
      user_id: 'U1',
      item_name: reqInput.product,
      full_price: reqInput.amount,
      desired_date: reqInput.desired_date,
    };

    const decision = evaluateDecision(
      internalReq,
      reqInput.start_balance,
      reqInput.events,
      reqInput.payment_options,
      '2026-09-12',
      reqInput.minimum_safety_buffer
    );

    // Validate generated decision row against rules
    validateRow(decision, reqInput);

    // Escape CSV values if they contain commas or quotes
    const escapeCsv = (val: any) => {
      const str = String(val);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const csvRow = [
      escapeCsv(decision.request_id),
      escapeCsv(decision.amount_safe_to_pay),
      escapeCsv(decision.affordability_status),
      escapeCsv(decision.recommended_payment_method),
      escapeCsv(decision.payment_plan),
      escapeCsv(decision.earliest_date_for_full_payment),
      escapeCsv(decision.spending_changes_needed),
      escapeCsv(decision.decision_explanation),
    ].join(',');

    rows.push(csvRow);
    console.log(`✓ Processed & Validated Request ${decision.request_id} (${reqInput.product})`);
  }

  const csvContent = rows.join('\n') + '\n';

  // Write output.csv to project root and backend folder
  fs.writeFileSync(path.join(process.cwd(), 'output.csv'), csvContent, 'utf-8');
  fs.writeFileSync(path.join(process.cwd(), 'backend', 'output.csv'), csvContent, 'utf-8');

  console.log('\n=======================================================');
  console.log('OUTPUT.CSV GENERATION & VALIDATION SUCCESSFUL!');
  console.log(`File created at: ${path.join(process.cwd(), 'output.csv')}`);
  console.log('=======================================================\n');
}

generateCSVOutput();
