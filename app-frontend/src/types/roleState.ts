export interface ActorState {
  posture?: string;
  clothing?: string;
  location?: string;
}

export interface RoleState {
  scene?: string | null;
  characters?: Record<string, ActorState>;
}

export interface RoleStateSnapshot {
  session_id: number;
  state: RoleState;
  revision: string;
}

export interface RoleStatePatch {
  scene?: string | null;
  characters?: Record<string, { [K in keyof ActorState]?: string | null }>;
}
