import { FinancialEvent } from './types.js';
import { run90DayForecast } from './forecast.js';

export function calculateAmountSafeToPay(
  requested_amount: number,
  start_balance: number,
  events: FinancialEvent[],
  as_of_date: string = '2026-09-12',
  minimum_safety_buffer: number = 1000.0
): number {
  if (requested_amount <= 0) return 0.0;

  let low = 0;
  let high = Math.max(0, start_balance - minimum_safety_buffer);
  high = Math.min(requested_amount, high);

  if (high <= 0) return 0.0;

  let best = 0.0;

  // Binary search to find the exact maximum upfront amount safe across the 90-day horizon
  for (let step = 0; step < 20; step++) {
    const mid = Math.round(((low + high) / 2) * 100) / 100;
    const testSchedule = new Map<string, number>();
    testSchedule.set(as_of_date, mid);

    const fc = run90DayForecast(
      start_balance,
      events,
      testSchedule,
      as_of_date,
      minimum_safety_buffer
    );

    if (fc.is_safe) {
      best = mid;
      low = mid + 0.01;
    } else {
      high = mid - 0.01;
    }

    if (high < low) break;
  }

  return Math.max(0, Math.min(requested_amount, Math.round(best * 100) / 100));
}
