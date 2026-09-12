import { PurchaseRequest, FinancialEvent, DecisionOutput, PaymentOption, FinancialFactor, ForecastSummary } from './types.js';
import { run90DayForecast } from './forecast.js';
import { calculateAmountSafeToPay } from './amountSafe.js';
import { findSpendingChanges } from './spendingOptimizer.js';
import { generateExplanation } from './explanation.js';

export function evaluateDecision(
  request: PurchaseRequest,
  start_balance: number,
  events: FinancialEvent[],
  payment_options?: PaymentOption[],
  as_of_date: string = '2026-09-12',
  minimum_safety_buffer: number = 1000.0
): DecisionOutput {
  const req_id = request.request_id || 'R001';
  const price = request.full_price !== undefined ? request.full_price : (request.amount !== undefined ? request.amount : 0);
  const desired_date = request.desired_date || request.offer_expires_at || as_of_date;

  // 1. Calculate Safe Amount Today
  const amount_safe_today = calculateAmountSafeToPay(
    price,
    start_balance,
    events,
    as_of_date,
    minimum_safety_buffer
  );

  // 2. Base 90-day baseline forecast
  const baseForecast = run90DayForecast(
    start_balance,
    events,
    new Map(),
    as_of_date,
    minimum_safety_buffer
  );

  const forecastSummary: ForecastSummary = {
    minimum_projected_balance: baseForecast.minimum_balance,
    lowest_balance_date: baseForecast.lowest_day_date,
    safety_buffer_required: minimum_safety_buffer,
    horizon_days: 90,
  };

  const financialFactors: FinancialFactor[] = [
    {
      factor: 'Starting Account Balance',
      impact: start_balance >= price ? 'positive' : 'negative',
      description: `Available cash buffer of $${start_balance.toFixed(2)} as of ${as_of_date}.`,
    },
    {
      factor: 'Liquidity Safety Reserve',
      impact: 'neutral',
      description: `Mandatory safety buffer of $${minimum_safety_buffer.toFixed(2)} strictly preserved.`,
    },
    {
      factor: 'Safe Upfront Amount Today',
      impact: amount_safe_today > 0 ? 'positive' : 'negative',
      description: `Calculated maximum upfront liquid amount safe to pay today is $${amount_safe_today.toFixed(2)}.`,
    },
  ];

  // 3. Evaluate Full Upfront Today
  const upfrontSchedule = new Map<string, number>();
  upfrontSchedule.set(as_of_date, price);

  const upfrontForecast = run90DayForecast(
    start_balance,
    events,
    upfrontSchedule,
    as_of_date,
    minimum_safety_buffer
  );

  if (upfrontForecast.is_safe) {
    const plan_str = `${as_of_date}:${price}`;
    const exp = generateExplanation(
      request,
      start_balance,
      'affordable_now',
      'full_payment',
      as_of_date,
      'none',
      minimum_safety_buffer
    );

    return {
      request_id: req_id,
      amount_safe_to_pay: amount_safe_today,
      affordability_status: 'affordable_now',
      recommended_payment_method: 'full_payment',
      payment_plan: plan_str,
      earliest_date_for_full_payment: as_of_date,
      spending_changes_needed: 'none',
      decision_explanation: exp,

      // Stitch UI Aliases
      decision: 'affordable_now',
      safe_amount: amount_safe_today,
      payment_method: 'full_payment',
      earliest_date: as_of_date,
      spending_changes: 'none',
      explanation: exp,
      financial_factors: financialFactors,
      forecast_summary: forecastSummary,
    };
  }

  // 4. Evaluate Available Payment Options (BNPL Installments, Partial Payment)
  if (payment_options && payment_options.length > 0) {
    for (const opt of payment_options) {
      if (opt.type === 'BNPL_INSTALLMENTS' && opt.installment_amount && opt.num_installments) {
        const instSchedule = new Map<string, number>();
        const down = opt.down_payment !== undefined ? opt.down_payment : opt.installment_amount;
        instSchedule.set(as_of_date, down);

        const startDate = new Date(as_of_date);
        const freq = opt.frequency_days || 14;

        for (let i = 1; i < opt.num_installments; i++) {
          const d = new Date(startDate);
          d.setDate(d.getDate() + i * freq);
          const dateStr = d.toISOString().split('T')[0];
          instSchedule.set(dateStr, opt.installment_amount);
        }

        const instForecast = run90DayForecast(
          start_balance,
          events,
          instSchedule,
          as_of_date,
          minimum_safety_buffer
        );

        if (instForecast.is_safe) {
          const planParts: string[] = [];
          for (const [dStr, amt] of instSchedule.entries()) {
            planParts.push(`${dStr}:${amt}`);
          }
          const plan_str = planParts.join(', ');

          const exp = generateExplanation(
            request,
            start_balance,
            'affordable_with_plan',
            'installments',
            as_of_date,
            'none',
            minimum_safety_buffer
          );

          return {
            request_id: req_id,
            amount_safe_to_pay: amount_safe_today,
            affordability_status: 'affordable_with_plan',
            recommended_payment_method: 'installments',
            payment_plan: plan_str,
            earliest_date_for_full_payment: as_of_date,
            spending_changes_needed: 'none',
            decision_explanation: exp,

            // Stitch UI Aliases
            decision: 'affordable_with_plan',
            safe_amount: amount_safe_today,
            payment_method: 'installments',
            earliest_date: as_of_date,
            spending_changes: 'none',
            explanation: exp,
            financial_factors: financialFactors,
            forecast_summary: forecastSummary,
          };
        }
      } else if (opt.type === 'PARTIAL' && opt.down_payment) {
        const partialSchedule = new Map<string, number>();
        partialSchedule.set(as_of_date, opt.down_payment);
        const remainder = Math.max(0, price - opt.down_payment);
        if (remainder > 0) {
          partialSchedule.set(desired_date, remainder);
        }

        const partialForecast = run90DayForecast(
          start_balance,
          events,
          partialSchedule,
          as_of_date,
          minimum_safety_buffer
        );

        if (partialForecast.is_safe) {
          const planParts = [`${as_of_date}:${opt.down_payment}`];
          if (remainder > 0) planParts.push(`${desired_date}:${remainder}`);
          const plan_str = planParts.join(', ');

          const exp = generateExplanation(
            request,
            start_balance,
            'affordable_with_plan',
            'partial_payment',
            as_of_date,
            'none',
            minimum_safety_buffer
          );

          return {
            request_id: req_id,
            amount_safe_to_pay: amount_safe_today,
            affordability_status: 'affordable_with_plan',
            recommended_payment_method: 'partial_payment',
            payment_plan: plan_str,
            earliest_date_for_full_payment: desired_date,
            spending_changes_needed: 'none',
            decision_explanation: exp,

            // Stitch UI Aliases
            decision: 'affordable_with_plan',
            safe_amount: amount_safe_today,
            payment_method: 'partial_payment',
            earliest_date: desired_date,
            spending_changes: 'none',
            explanation: exp,
            financial_factors: financialFactors,
            forecast_summary: forecastSummary,
          };
        }
      }
    }
  }

  // 5. Evaluate Waiting until desired_date
  const waitSchedule = new Map<string, number>();
  waitSchedule.set(desired_date, price);

  const waitForecast = run90DayForecast(
    start_balance,
    events,
    waitSchedule,
    as_of_date,
    minimum_safety_buffer
  );

  if (waitForecast.is_safe) {
    const plan_str = `${desired_date}:${price}`;
    const exp = generateExplanation(
      request,
      start_balance,
      'affordable_later',
      'wait',
      desired_date,
      'none',
      minimum_safety_buffer
    );

    return {
      request_id: req_id,
      amount_safe_to_pay: amount_safe_today,
      affordability_status: 'affordable_later',
      recommended_payment_method: 'wait',
      payment_plan: plan_str,
      earliest_date_for_full_payment: desired_date,
      spending_changes_needed: 'none',
      decision_explanation: exp,

      // Stitch UI Aliases
      decision: 'affordable_later',
      safe_amount: amount_safe_today,
      payment_method: 'wait',
      earliest_date: desired_date,
      spending_changes: 'none',
      explanation: exp,
      financial_factors: financialFactors,
      forecast_summary: forecastSummary,
    };
  }

  // 6. Evaluate Spending Changes
  const optRes = findSpendingChanges(
    price,
    start_balance,
    events,
    desired_date,
    as_of_date,
    minimum_safety_buffer
  );

  if (optRes.action_str !== 'none') {
    const plan_str = `${desired_date}:${price}`;
    const exp = generateExplanation(
      request,
      start_balance,
      'affordable_later',
      'wait',
      desired_date,
      optRes.action_str,
      minimum_safety_buffer
    );

    return {
      request_id: req_id,
      amount_safe_to_pay: amount_safe_today,
      affordability_status: 'affordable_later',
      recommended_payment_method: 'wait',
      payment_plan: plan_str,
      earliest_date_for_full_payment: desired_date,
      spending_changes_needed: optRes.action_str,
      decision_explanation: exp,

      // Stitch UI Aliases
      decision: 'affordable_later',
      safe_amount: amount_safe_today,
      payment_method: 'wait',
      earliest_date: desired_date,
      spending_changes: optRes.action_str,
      explanation: exp,
      financial_factors: financialFactors,
      forecast_summary: forecastSummary,
    };
  }

  // 7. Otherwise: Not Affordable
  const exp = generateExplanation(
    request,
    start_balance,
    'not_affordable',
    'not_recommended',
    as_of_date,
    'none',
    minimum_safety_buffer
  );

  return {
    request_id: req_id,
    amount_safe_to_pay: amount_safe_today,
    affordability_status: 'not_affordable',
    recommended_payment_method: 'not_recommended',
    payment_plan: 'none',
    earliest_date_for_full_payment: as_of_date,
    spending_changes_needed: 'none',
    decision_explanation: exp,

    // Stitch UI Aliases
    decision: 'not_affordable',
    safe_amount: amount_safe_today,
    payment_method: 'not_recommended',
    earliest_date: as_of_date,
    spending_changes: 'none',
    explanation: exp,
    financial_factors: financialFactors,
    forecast_summary: forecastSummary,
  };
}
