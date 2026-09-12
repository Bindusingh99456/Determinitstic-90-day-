import { FinancialEvent } from './types.js';
import { run90DayForecast } from './forecast.js';

export interface OptimizationResult {
  action_str: string; // e.g. "stop:EVT_SUB" or "none"
  modified_events: FinancialEvent[];
}

export function findSpendingChanges(
  requested_amount: number,
  start_balance: number,
  events: FinancialEvent[],
  desired_date: string,
  as_of_date: string = '2026-09-12',
  minimum_safety_buffer: number = 1000.0
): OptimizationResult {
  // Identify flexible non-essential recurring expenses (subscriptions, discretionary)
  const flexible = events.filter(
    (e) =>
      e.status === 'CONFIRMED' &&
      e.event_type === 'EXPENSE' &&
      (e.is_essential === false || e.category === 'SUBSCRIPTION' || e.category === 'ENTERTAINMENT')
  );

  if (flexible.length === 0) {
    return { action_str: 'none', modified_events: events };
  }

  // Rank flexible events: lower amount first
  flexible.sort((a, b) => a.amount - b.amount);

  for (const flex_evt of flexible) {
    const modified = events.filter((e) => e.event_id !== flex_evt.event_id);
    const schedule = new Map<string, number>();
    schedule.set(desired_date, requested_amount);

    const fc = run90DayForecast(
      start_balance,
      modified,
      schedule,
      as_of_date,
      minimum_safety_buffer
    );

    if (fc.is_safe) {
      return {
        action_str: `stop:${flex_evt.event_id}`,
        modified_events: modified,
      };
    }
  }

  return { action_str: 'none', modified_events: events };
}
