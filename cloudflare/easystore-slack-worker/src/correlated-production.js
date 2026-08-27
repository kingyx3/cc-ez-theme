import productionWorker, {
  makeQueueSafeMessage,
  prepareWorkflowQueueMessage,
} from "./production.js";
import {
  OrderCorrelation,
  correlateWorkflowOrder,
} from "./order-correlation.js";

export { OrderCorrelation };

export default {
  fetch(request, env, ctx) {
    if (!isWorkflowMode(env.SLACK_MODE) || !env.OUTBOUND_QUEUE?.send) {
      return productionWorker.fetch(request, env, ctx);
    }

    const queue = env.OUTBOUND_QUEUE;
    const wrappedEnv = {
      ...env,
      OUTBOUND_QUEUE: {
        async send(body, options) {
          const correlated = await correlateWorkflowOrder(body, env);
          const prepared = prepareWorkflowQueueMessage(correlated);
          return queue.send(makeQueueSafeMessage(prepared), options);
        },
      },
    };

    return productionWorker.fetch(request, wrappedEnv, ctx);
  },

  queue(batch, env, ctx) {
    return productionWorker.queue(batch, env, ctx);
  },
};

function isWorkflowMode(value) {
  return String(value ?? "").trim().toLowerCase() === "workflow";
}
