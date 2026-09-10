export const PROCESS_OPERATIONS = ["cutting", "printing", "sewing", "packaging", "storage_transfer"] as const;

export type TimelineStage = {
  operation: string;
  status: string;
  planned: number;
  completed: number;
  received_qty?: number;
  output_qty?: number;
  failed?: number;
  processed?: number;
  has_open_replacements?: boolean;
  is_blocked?: boolean;
  block_reason?: string | null;
  overdue?: boolean;
};

export type TimelineState = "completed" | "accepted" | "partialAcceptance" | "waitingAcceptance" | "partial" | "waiting" | "notStarted" | "skipped" | "blocked" | "cancelled" | "rejected";

const quantity = (value: unknown) => Math.max(0, Number(value) || 0);

export function processTimeline(stages: TimelineStage[]) {
  const byOperation = new Map(stages.map(stage => [stage.operation, stage]));
  let available = 0;
  return PROCESS_OPERATIONS.map(operation => {
    const stage = byOperation.get(operation);
    const ready = available;
    if (stage) available = quantity(stage.completed);
    const planned = quantity(stage?.planned);
    const output = quantity(stage?.output_qty ?? stage?.completed);
    const received = quantity(stage?.received_qty);
    const awaiting = Math.max(0, ready - received);
    let state: TimelineState;
    if (!stage) {
      state = operation === "printing" && stages.length > 0 ? "skipped" : "notStarted";
    } else if (stage.is_blocked) {
      state = "blocked";
    } else if (stage.status === "cancelled" || stage.status === "rejected") {
      state = stage.status;
    } else if (operation === "sewing") {
      // Automatic workflow activation is not a receipt. Even a planned line
      // assignment does not establish that sewing has accepted any pieces.
      if (received > 0) state = awaiting > 0 ? "partialAcceptance" : "accepted";
      else if (ready > 0) state = "waitingAcceptance";
      else if (stage.status === "completed" && output > 0) state = "completed";
      else state = "notStarted";
    } else if (stage.status === "completed" && !stage.has_open_replacements && (
      planned === 0 || output >= planned || (operation === "cutting" && output > 0)
    )) {
      // Cutting can close with an accepted shortage. Its original plan and
      // real output remain visible; they do not override the saved closure.
      state = "completed";
    } else if (output > 0) {
      state = "partial";
    } else if (ready > 0) {
      state = "waiting";
    } else {
      state = "notStarted";
    }
    const tone = state === "completed" || state === "accepted" ? "green"
      : ["partial", "partialAcceptance", "waiting", "waitingAcceptance"].includes(state) ? "yellow"
      : state === "blocked" || state === "rejected" ? "red" : "gray";
    return { operation, stage, state, tone, planned, output, received, ready, awaiting };
  });
}
