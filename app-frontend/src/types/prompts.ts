export interface TokenEstimateDetail {
  characters: number;
  estimated_tokens: number;
  lower_bound: number;
  upper_bound: number;
}

export interface TokenEstimate {
  characters: number;
  estimated_tokens: number;
  lower_bound: number;
  upper_bound: number;
  method: string;
  is_exact: boolean;
  sections: Record<string, TokenEstimateDetail>;
}

export interface CompiledPromptResponse {
  messages: { role: string; content: string }[];
  token_estimate?: TokenEstimate;
}
