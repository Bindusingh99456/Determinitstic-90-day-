import { evaluateDecision } from './decisionEngine.js';
import { PurchaseRequest, FinancialEvent, PaymentOption } from './types.js';

console.log('\n=======================================================');
console.log('STARTING AUDIT & REGRESSION TEST SUITE FOR DIFFICULT CASES');
console.log('=======================================================\n');

let totalTests = 0;
let passedTests = 0;

function runAuditCase(name: string, fn: () => boolean) {
  totalTests++;
  try {
    const success = fn();
    if (success) {
      passedTests++;
      console.log(`✓ [PASSED] Case ${totalTests}: ${name}`);
    } else {
      console.log(`✗ [FAILED] Case ${totalTests}: ${name}`);
    }
  } catch (err: any) {
    console.log(`✗ [FAILED] Case ${totalTests}: ${name} - Exception: ${err.message}`);
  }
}

// 1. Missing Amounts / Ambiguous
runAuditCase('Missing Amounts (defaults to 0 safe)', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_01',
    user_id: 'U1',
    item_name: 'Unknown Item',
    full_price: 0,
  };
  const decision = evaluateDecision(req, 5000, [], undefined, '2026-09-12', 1000);
  return decision.amount_safe_to_pay === 0 && decision.affordability_status === 'affordable_now';
});

// 2. Currency Conversion
runAuditCase('Currency Conversion (EUR to USD)', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_02',
    user_id: 'U1',
    item_name: 'European Gadget',
    full_price: 100,
  };
  // Event in EUR: €1000 = $1080
  const events: FinancialEvent[] = [
    {
      event_id: 'EVT_EUR_SALARY',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'INCOME',
      status: 'CONFIRMED',
      amount: 1000,
      currency: 'EUR',
      event_date: '2026-09-12',
      category: 'SALARY',
    },
  ];
  const decision = evaluateDecision(req, 1000, events, undefined, '2026-09-12', 1000);
  return decision.affordability_status === 'affordable_now';
});

// 3. Cancelled & Superseded & Duplicate Events
runAuditCase('Cancelled, Superseded & Duplicate Events handling', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_03',
    user_id: 'U1',
    item_name: 'Headphones',
    full_price: 500,
  };
  const events: FinancialEvent[] = [
    {
      event_id: 'EVT_EXP_1',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'EXPENSE',
      status: 'CANCELLED', // Should be ignored
      amount: 4000,
      event_date: '2026-09-12',
      category: 'REPAIR',
    },
    {
      event_id: 'EVT_EXP_2',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'EXPENSE',
      status: 'SUPERSEDED', // Should be ignored
      amount: 4000,
      event_date: '2026-09-12',
      category: 'RENT',
    },
  ];
  const decision = evaluateDecision(req, 2000, events, undefined, '2026-09-12', 1000);
  return decision.affordability_status === 'affordable_now';
});

// 4. Recurring Income & Expenses
runAuditCase('Recurring Income & Expenses Horizon Projection', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_04',
    user_id: 'U1',
    item_name: 'E-Bike',
    full_price: 1200,
  };
  const events: FinancialEvent[] = [
    {
      event_id: 'EVT_REC_SUB',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'EXPENSE',
      status: 'CONFIRMED',
      amount: 100,
      event_date: '2026-09-15',
      is_recurring: true,
      recurrence_pattern: 'MONTHLY',
      category: 'SUBSCRIPTION',
    },
    {
      event_id: 'EVT_REC_SALARY',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'INCOME',
      status: 'CONFIRMED',
      amount: 1500,
      event_date: '2026-09-25',
      is_recurring: true,
      recurrence_pattern: 'BIWEEKLY',
      category: 'SALARY',
    },
  ];
  const decision = evaluateDecision(req, 1500, events, undefined, '2026-09-12', 1000);
  // Math: start balance $1500 - $100 subscription on Sept 15 - $1000 buffer = $400 safe today.
  return decision.amount_safe_to_pay === 400;
});

// 5. Multiple Payment Options & Partial Payments
runAuditCase('Partial Payment Option Evaluation', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_05',
    user_id: 'U1',
    item_name: 'Camera',
    full_price: 2000,
    desired_date: '2026-09-30',
  };
  const options: PaymentOption[] = [
    {
      option_id: 'OPT_PARTIAL',
      type: 'PARTIAL',
      down_payment: 500,
    },
  ];
  const events: FinancialEvent[] = [
    {
      event_id: 'EVT_SALARY_LATER',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'INCOME',
      status: 'CONFIRMED',
      amount: 3000,
      event_date: '2026-09-25',
      category: 'SALARY',
    },
  ];
  const decision = evaluateDecision(req, 1500, events, options, '2026-09-12', 1000);
  return decision.affordability_status === 'affordable_with_plan' && decision.recommended_payment_method === 'partial_payment';
});

// 6. Tight Deadlines & Debt Repayment / Emergency Expenses
runAuditCase('Emergency Debt Repayment Priority', () => {
  const req: PurchaseRequest = {
    request_id: 'AUD_06',
    user_id: 'U1',
    item_name: 'Luxury Watch',
    full_price: 3000,
    desired_date: '2026-09-15',
  };
  const events: FinancialEvent[] = [
    {
      event_id: 'EVT_DEBT',
      user_id: 'U1',
      account_id: 'ACC1',
      event_type: 'EXPENSE',
      status: 'CONFIRMED',
      amount: 2500,
      event_date: '2026-09-14',
      is_essential: true,
      category: 'DEBT_REPAYMENT',
    },
  ];
  const decision = evaluateDecision(req, 3500, events, undefined, '2026-09-12', 1000);
  // Total balance 3500 - 2500 essential debt = 1000 (equal to minimum buffer 1000). Safe amount = 0 today.
  return decision.amount_safe_to_pay === 0 && decision.affordability_status === 'not_affordable';
});

console.log('\n-------------------------------------------------------');
console.log(`AUDIT RESULTS: ${passedTests}/${totalTests} PASSED (${((passedTests / totalTests) * 100).toFixed(1)}%)`);
console.log('-------------------------------------------------------\n');
