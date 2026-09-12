import { FinancialEvent } from './types.js';

export interface CashflowDailyState {
  date: string;
  day_index: number;
  balance: number;
  inflow: number;
  outflow: number;
}

export interface ForecastResult {
  is_safe: boolean;
  minimum_balance: number;
  lowest_day_date: string;
  daily_states: CashflowDailyState[];
  violation_reason?: string;
}

const CURRENCY_RATES: Record<string, number> = {
  USD: 1.0,
  EUR: 1.08,
  GBP: 1.27,
  CAD: 0.74,
  AUD: 0.65,
  INR: 0.012,
  JPY: 0.0067,
};

function getConvertedAmount(amount: number, currency?: string): number {
  if (!currency) return amount;
  const upperCurr = currency.toUpperCase().trim();
  const rate = CURRENCY_RATES[upperCurr] || 1.0;
  return amount * rate;
}

function normalizeEvents(events: FinancialEvent[]): FinancialEvent[] {
  // 1. Remove superseded events referenced by linked_event_id / related_event_id
  const supersededIds = new Set<string>();
  for (const e of events) {
    if (e.linked_event_id) supersededIds.add(e.linked_event_id);
    if (e.related_event_id && e.status === 'SUPERSEDED') supersededIds.add(e.related_event_id);
  }

  // 2. Deduplicate by event_id (keep latest CONFIRMED)
  const eventMap = new Map<string, FinancialEvent>();
  for (const e of events) {
    if (e.status === 'CANCELLED' || e.status === 'SUPERSEDED') continue;
    if (supersededIds.has(e.event_id)) continue;

    // Deduplicate
    if (!eventMap.has(e.event_id) || e.status === 'CONFIRMED') {
      eventMap.set(e.event_id, e);
    }
  }

  return Array.from(eventMap.values());
}

function isEventOnDate(evt: FinancialEvent, dateStr: string, startDateStr: string): boolean {
  if (evt.event_date === dateStr) return true;

  if (evt.is_recurring) {
    const eDate = new Date(evt.event_date);
    const cDate = new Date(dateStr);

    if (cDate < eDate) return false;

    const diffDays = Math.round((cDate.getTime() - eDate.getTime()) / (1000 * 3600 * 24));
    if (diffDays <= 0) return false;

    const pattern = (evt.recurrence_pattern || '').toUpperCase();

    if (pattern === 'DAILY') {
      return true;
    } else if (pattern === 'WEEKLY') {
      return diffDays % 7 === 0;
    } else if (pattern === 'BIWEEKLY' || pattern === 'EVERY_14_DAYS') {
      return diffDays % 14 === 0;
    } else if (pattern === 'MONTHLY' || pattern === 'EVERY_30_DAYS') {
      // Compare day of month or 30-day interval
      return cDate.getDate() === eDate.getDate() || diffDays % 30 === 0;
    } else {
      // Default recurring fallback (e.g., salary bi-weekly or monthly)
      if (evt.category === 'SALARY') {
        return diffDays % 14 === 0;
      }
      return diffDays % 30 === 0;
    }
  }

  return false;
}

export function run90DayForecast(
  start_balance: number,
  raw_events: FinancialEvent[],
  payments_schedule: Map<string, number>, // YYYY-MM-DD -> amount
  as_of_date: string = '2026-09-12',
  minimum_safety_buffer: number = 1000.0,
  horizon_days: number = 90
): ForecastResult {
  const events = normalizeEvents(raw_events);

  let current_balance = start_balance;
  let min_balance = start_balance;
  let lowest_date = as_of_date;
  let is_safe = true;
  let violation_reason: string | undefined = undefined;

  const startDate = new Date(as_of_date);
  const dailyStates: CashflowDailyState[] = [];

  for (let day = 0; day <= horizon_days; day++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + day);
    const dateStr = d.toISOString().split('T')[0];

    let dayInflow = 0;
    let dayOutflow = 0;

    // Process confirmed events on this date
    for (const evt of events) {
      if (evt.status !== 'CONFIRMED') continue;

      if (isEventOnDate(evt, dateStr, as_of_date)) {
        const amt = getConvertedAmount(evt.amount, evt.currency);
        if (evt.event_type === 'INCOME') {
          dayInflow += amt;
        } else if (evt.event_type === 'EXPENSE') {
          dayOutflow += amt;
        }
      }
    }

    // Process purchase payments on this date
    if (payments_schedule.has(dateStr)) {
      dayOutflow += payments_schedule.get(dateStr) || 0;
    }

    current_balance += dayInflow - dayOutflow;

    if (current_balance < min_balance) {
      min_balance = current_balance;
      lowest_date = dateStr;
    }

    if (current_balance < minimum_safety_buffer) {
      is_safe = false;
      if (!violation_reason) {
        violation_reason = `Balance dropped to $${current_balance.toFixed(2)} on ${dateStr}, below safety buffer of $${minimum_safety_buffer.toFixed(2)}.`;
      }
    }

    dailyStates.push({
      date: dateStr,
      day_index: day,
      balance: current_balance,
      inflow: dayInflow,
      outflow: dayOutflow,
    });
  }

  return {
    is_safe,
    minimum_balance: min_balance,
    lowest_day_date: lowest_date,
    daily_states: dailyStates,
    violation_reason,
  };
}
