import { evaluateDecision } from './decisionEngine.js';
import { PurchaseRequest, FinancialEvent, PaymentOption } from './types.js';

interface TestCase {
  request_id: string;
  product: string;
  amount: number;
  desired_date: string;
  start_balance: number;
  minimum_safety_buffer: number;
  events: FinancialEvent[];
  payment_options?: PaymentOption[];
  expected: {
    amount_safe_to_pay: number;
    affordability_status: string;
    recommended_payment_method: string;
    payment_plan: string;
    earliest_date_for_full_payment: string;
    spending_changes_needed: string;
  };
}

const sampleTestCases: TestCase[] = [
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
    expected: {
      amount_safe_to_pay: 10000,
      affordability_status: 'affordable_later',
      recommended_payment_method: 'wait',
      payment_plan: '2026-09-30:60000',
      earliest_date_for_full_payment: '2026-09-30',
      spending_changes_needed: 'none',
    },
  },
  {
    request_id: 'R002',
    product: 'Smart Watch',
    amount: 800,
    desired_date: '2026-09-12',
    start_balance: 5000,
    minimum_safety_buffer: 1000,
    events: [],
    expected: {
      amount_safe_to_pay: 800,
      affordability_status: 'affordable_now',
      recommended_payment_method: 'full_payment',
      payment_plan: '2026-09-12:800',
      earliest_date_for_full_payment: '2026-09-12',
      spending_changes_needed: 'none',
    },
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
    expected: {
      amount_safe_to_pay: 800,
      affordability_status: 'affordable_with_plan',
      recommended_payment_method: 'installments',
      payment_plan: '2026-09-12:300, 2026-09-26:300, 2026-10-10:300, 2026-10-24:300, 2026-11-07:300',
      earliest_date_for_full_payment: '2026-09-12',
      spending_changes_needed: 'none',
    },
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
    expected: {
      amount_safe_to_pay: 200,
      affordability_status: 'affordable_later',
      recommended_payment_method: 'wait',
      payment_plan: '2026-10-01:1000',
      earliest_date_for_full_payment: '2026-10-01',
      spending_changes_needed: 'stop:EVT_SUB',
    },
  },
  {
    request_id: 'R005',
    product: 'Vacation',
    amount: 50000,
    desired_date: '2026-09-12',
    start_balance: 2000,
    minimum_safety_buffer: 1000,
    events: [],
    expected: {
      amount_safe_to_pay: 1000,
      affordability_status: 'not_affordable',
      recommended_payment_method: 'not_recommended',
      payment_plan: 'none',
      earliest_date_for_full_payment: '2026-09-12',
      spending_changes_needed: 'none',
    },
  },
];

export function runBenchmark(): boolean {
  console.log('\n=======================================================');
  console.log('BENCHMARK EVALUATION OF SAMPLE REQUESTS');
  console.log(`Total Test Requests: ${sampleTestCases.length}`);
  console.log('=======================================================\n');

  let passed = 0;

  for (const tc of sampleTestCases) {
    const req: PurchaseRequest = {
      request_id: tc.request_id,
      user_id: 'U1',
      item_name: tc.product,
      full_price: tc.amount,
      desired_date: tc.desired_date,
    };

    const actual = evaluateDecision(
      req,
      tc.start_balance,
      tc.events,
      tc.payment_options,
      '2026-09-12',
      tc.minimum_safety_buffer
    );

    let tcPassed = true;
    const errors: string[] = [];

    for (const [key, expVal] of Object.entries(tc.expected)) {
      const actVal = (actual as any)[key];
      if (key === 'amount_safe_to_pay') {
        if (Math.abs(Number(actVal) - Number(expVal)) > 0.01) {
          tcPassed = false;
          errors.push(`- ${key}: Expected '${expVal}', Got '${actVal}'`);
        }
      } else {
        if (String(actVal).trim() !== String(expVal).trim()) {
          tcPassed = false;
          errors.push(`- ${key}: Expected '${expVal}', Got '${actVal}'`);
        }
      }
    }

    if (tcPassed) {
      passed++;
      console.log(`✓ Request ${tc.request_id} (${tc.product}): PASSED ALL FIELDS`);
    } else {
      console.log(`✗ Request ${tc.request_id} (${tc.product}): MISMATCH DETECTED`);
      for (const err of errors) {
        console.log(`   ${err}`);
      }
    }
  }

  console.log('\n-------------------------------------------------------');
  console.log(`BENCHMARK RESULT: ${passed}/${sampleTestCases.length} PASSED (${((passed / sampleTestCases.length) * 100).toFixed(1)}%)`);
  console.log('-------------------------------------------------------\n');

  return passed === sampleTestCases.length;
}

runBenchmark();
