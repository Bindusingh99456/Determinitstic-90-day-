export interface FinancialEvent {
  event_id: string;
  user_id: string;
  account_id: string;
  event_type: 'EXPENSE' | 'INCOME' | 'TRANSFER';
  status: 'CONFIRMED' | 'PENDING' | 'SUPERSEDED' | 'CANCELLED';
  amount: number;
  currency?: string;
  event_date: string; // YYYY-MM-DD
  is_recurring?: boolean;
  recurrence_pattern?: string;
  category: string;
  is_essential?: boolean;
  related_event_id?: string;
  linked_event_id?: string;
}

export interface PurchaseRequest {
  request_id: string;
  user_id: string;
  item_name: string;
  product?: string;
  full_price: number;
  amount?: number;
  desired_date?: string;
  offer_expires_at?: string;
}

export interface PaymentOption {
  option_id: string;
  type: 'UPFRONT' | 'PARTIAL' | 'BNPL_INSTALLMENTS' | 'CUSTOM_PLAN';
  down_payment?: number;
  installment_amount?: number;
  num_installments?: number;
  frequency_days?: number;
  upfront_fee?: number;
  apr_percent?: number;
}

export interface FinancialFactor {
  factor: string;
  impact: 'positive' | 'negative' | 'neutral';
  description: string;
}

export interface ForecastSummary {
  minimum_projected_balance: number;
  lowest_balance_date: string;
  safety_buffer_required: number;
  horizon_days: number;
}

export interface DecisionOutput {
  // Required competition CSV fields
  request_id: string;
  amount_safe_to_pay: number;
  affordability_status: 'affordable_now' | 'affordable_with_plan' | 'affordable_later' | 'not_affordable';
  recommended_payment_method: 'full_payment' | 'partial_payment' | 'installments' | 'wait' | 'not_recommended';
  payment_plan: string;
  earliest_date_for_full_payment: string;
  spending_changes_needed: string;
  decision_explanation: string;

  // Stitch Frontend Compatibility Aliases & Rich Extended Information
  decision?: 'affordable_now' | 'affordable_with_plan' | 'affordable_later' | 'not_affordable';
  safe_amount?: number;
  payment_method?: 'full_payment' | 'partial_payment' | 'installments' | 'wait' | 'not_recommended';
  earliest_date?: string;
  spending_changes?: string;
  explanation?: string;
  financial_factors?: FinancialFactor[];
  forecast_summary?: ForecastSummary;
}
