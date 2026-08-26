import worker from "./index.js";

const MAX_QUEUE_STRING_LENGTH = 1000;
const MAX_QUEUE_ARRAY_ITEMS = 25;
const MAX_QUEUE_OBJECT_KEYS = 50;
const MAX_QUEUE_DEPTH = 8;

export default {
  fetch(request, env, ctx) {
    const queue = env.OUTBOUND_QUEUE;
    if (!queue?.send) return worker.fetch(request, env, ctx);

    const wrappedEnv = {
      ...env,
      OUTBOUND_QUEUE: {
        send(body, options) {
          return queue.send(makeQueueSafeMessage(body), options);
        },
      },
    };
    return worker.fetch(request, wrappedEnv, ctx);
  },

  queue(batch, env, ctx) {
    return worker.queue(batch, env, ctx);
  },
};

export function makeQueueSafeMessage(message) {
  return boundQueueValue(message, 0);
}

function boundQueueValue(value, depth) {
  if (value === null || value === undefined) return value ?? null;
  if (typeof value === "string") {
    return value.length <= MAX_QUEUE_STRING_LENGTH
      ? value
      : `${value.slice(0, MAX_QUEUE_STRING_LENGTH - 1)}…`;
  }
  if (["number", "boolean"].includes(typeof value)) return value;
  if (depth >= MAX_QUEUE_DEPTH) return "[truncated]";

  if (Array.isArray(value)) {
    return value
      .slice(0, MAX_QUEUE_ARRAY_ITEMS)
      .map((item) => boundQueueValue(item, depth + 1));
  }

  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, MAX_QUEUE_OBJECT_KEYS)
        .map(([key, nested]) => [key, boundQueueValue(nested, depth + 1)]),
    );
  }

  return String(value).slice(0, MAX_QUEUE_STRING_LENGTH);
}
