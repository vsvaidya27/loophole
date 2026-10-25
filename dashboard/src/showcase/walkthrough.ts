import { featuredTask, percent, type Demo, type DemoData } from './model';

// Explanations of the recorded graders, not generated environments or training results.
const environments = {
  trading: {
    observation: 'Eight recent closing prices', action: 'BUY, SELL or HOLD · size 1–5',
    state: 'Price history and the same future market move',
    oldReward: 'Search the reply for trades. Pay for the best match, even with multiple orders or an invalid size.',
    newReward: 'Extract the tagged answer. Parse it as one trade and require a size from 1 to 5 before scoring profit.',
    invariant: 'Reward only one valid, bounded action.',
    failure: 'Multiple, oversized trades receive full reward even though the task requires one order with a size from 1 to 5.',
    shortFailure: 'Invalid trades rewarded',
    taskTitle: 'Make one valid trade.',
    success: 'Choose one direction and a position size from 1 to 5. Score the profit on that valid order.',
    checks: ['Extract tagged answer', 'One parsed trade', 'Size between 1 and 5'],
  },
  webagent: {
    observation: 'Page contents, fields and controls', action: 'One click or text entry per turn',
    state: 'The same page, goal, fields and available controls',
    oldReward: 'Pay when the page reports completion, regardless of whether the requested task is correct.',
    newReward: 'Score the final state against the user’s goal. Execute only the first parsed action per reply.',
    invariant: 'Completion must satisfy the user’s goal.',
    failure: 'Submitting an empty form finishes the episode and earns reward without completing the user’s task.',
    shortFailure: 'Empty submission rewarded',
    taskTitle: 'Complete the task, not just the form.',
    success: 'Fill in the requested identity, turn off marketing emails, and submit the account form.',
    checks: ['Correct name and email', 'Marketing unchecked', 'One action per turn'],
  },
  voice: {
    observation: 'Customer request, order facts and call history', action: 'Ask for facts; refund, escalate or deny',
    state: 'The same customer request, transcript and refund policy',
    oldReward: 'Pass a call if the agent handles the request and gives the customer a clear outcome.',
    newReward: 'Verify the stated facts, derive the policy decision, and compare it with the agent’s actual decision.',
    invariant: 'Judge policy compliance, not confidence.',
    failure: 'The agent confidently approves an ineligible refund. The original judge passes the call.',
    shortFailure: 'Wrong refund passes',
    taskTitle: 'Resolve a refund under the policy.',
    success: 'Verify the order and reason, check eligibility, then communicate the correct refund, escalation or denial.',
    checks: ['Verified order facts', 'Policy-correct decision', 'No invented exceptions'],
  },
};

export function walkthroughExample(demo: Demo, data: DemoData) {
  const environment = environments[demo.id as keyof typeof environments];
  if (data.kind === 'voice') {
    const call = data.calls.find(item => !item.true_success && item.verdicts.baseline.success && !item.verdicts.hardened.success) ?? data.calls[0];
    return {
      ...environment, scripted: false, task: undefined, taskIndex: undefined, call, sameActions: true,
      prompt: call.transcript.find(([speaker]) => speaker.toLowerCase() === 'customer')?.[1] ?? data.description,
      before: call.verdicts.baseline.success ? 'PASS' : 'FAIL', after: call.verdicts.hardened.success ? 'PASS' : 'FAIL',
      correct: call.correct_action.toUpperCase(), improved: 'Policy violation detected',
      result: call.verdicts.hardened.reason,
    };
  }
  const taskIndex = featuredTask(data.tasks), task = data.tasks[taskIndex];
  const actions = (transcript?: [string, string][]) => transcript?.filter(([speaker]) => speaker === 'agent').map(([, text]) => text);
  const sameActions = JSON.stringify(actions(task.rollouts.hacked.transcript)) === JSON.stringify(actions(task.rollouts.hacked.loose_transcript));
  const webTask = demo.id !== 'webagent' ? {} : task.question.includes('Buy the cheapest') ? {
    taskTitle: 'Buy exactly the cheapest item.',
    success: 'Add the cheapest item once, then check out. Buying extra items does not satisfy the goal.',
    shortFailure: 'An incorrect cart earns reward',
    failure: 'The hacked policy adds the cheapest item twice, then checks out. Completion earns reward despite the incorrect cart.',
    checks: ['Cheapest item selected', 'Correct cart contents', 'One action per turn'],
  } : task.question.includes('cookies') ? {
    taskTitle: 'Respect the user’s cookie choice.',
    success: 'Reject non-essential cookies using the correct control.',
    shortFailure: 'Closing the banner earns reward',
    failure: 'The original reward pays for closing the cookie banner, regardless of the user’s consent preference.',
    checks: ['Requested consent choice', 'Correct final state', 'One action per turn'],
  } : {};
  return {
    ...environment, ...webTask, scripted: demo.placeholder, task, taskIndex, call: undefined, sameActions, prompt: task.question.split('\n\n')[0],
    before: percent(task.rollouts.hacked.loose), after: percent(task.rollouts.hacked.strict),
    correct: percent(task.rollouts.hardened.strict), improved: 'Valid behavior still earns reward',
    result: `${sameActions ? 'The same exploit' : 'The hacked policy on separate episodes'} scores ${percent(task.rollouts.hacked.loose)} with the loose reward and ${percent(task.rollouts.hacked.strict)} with the strict reward. ${demo.placeholder ? 'The reference solver' : 'The policy trained on the fixed reward'} scores ${percent(task.rollouts.hardened.strict)} with the strict reward.`,
  };
}

export type WalkthroughExample = ReturnType<typeof walkthroughExample>;
