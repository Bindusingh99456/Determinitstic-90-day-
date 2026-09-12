import { PurchaseRequest } from './types.js';

export function generateExplanation(
  request: PurchaseRequest,
  start_balance: number,
  affordability_status: string,
  recommended_method: string,
  earliest_date: string,
  spending_changes: string,
  minimum_safety_buffer: number = 1000.0
): string {
  const item = request.item_name || request.product || 'the requested item';
  const price = request.full_price || request.amount || 0;

  if (affordability_status === 'affordable_now') {
    return `Buying ${item} today for $${price.toFixed(
      2
    )} is financially safe. Your available balance of $${start_balance.toFixed(
      2
    )} comfortably covers the purchase while keeping your balance above your required minimum of $${minimum_safety_buffer.toFixed(
      2
    )}.`;
  }

  if (affordability_status === 'affordable_with_plan') {
    if (recommended_method === 'partial_payment') {
      return `Buying ${item} upfront today for $${price.toFixed(
        2
      )} would drop your balance below your required minimum of $${minimum_safety_buffer.toFixed(
        2
      )}. Making a partial payment today and settling the balance on ${earliest_date} keeps your cashflow safe.`;
    }
    return `Buying ${item} upfront today for $${price.toFixed(
      2
    )} would drop your balance below your required minimum of $${minimum_safety_buffer.toFixed(
      2
    )}. However, using an installment plan keeps your payments spread out safely while maintaining your minimum balance.`;
  }

  if (affordability_status === 'affordable_later') {
    if (spending_changes && spending_changes !== 'none') {
      return `Buying ${item} today would reduce your balance below your required minimum of $${minimum_safety_buffer.toFixed(
        2
      )}. Applying spending change '${spending_changes}' allows full payment by ${earliest_date} while keeping your balance safe.`;
    }
    return `Buying ${item} today would reduce your balance below your required minimum of $${minimum_safety_buffer.toFixed(
      2
    )} because upcoming expenses are due before your next confirmed income. Waiting until ${earliest_date} allows the purchase while keeping your balance above the required minimum.`;
  }

  return `Buying ${item} today for $${price.toFixed(
    2
  )} is not recommended as your available balance of $${start_balance.toFixed(
    2
  )} cannot cover the purchase without violating your required minimum safety buffer of $${minimum_safety_buffer.toFixed(
    2
  )}.`;
}
