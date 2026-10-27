// What each plan includes. Every account is on 'free' today and free includes every hosted
// feature that exists. Paid tiers later: add the feature here, gate it with can(), and change
// users.plan. The plugin's local hooks are never gated.
export const PLANS = {
  free: { cloud_ledger: true, dashboard: true, weekly_report: false, team: false, shared_config: false },
  pro: { cloud_ledger: true, dashboard: true, weekly_report: true, team: false, shared_config: false },
  team: { cloud_ledger: true, dashboard: true, weekly_report: true, team: true, shared_config: true },
};

export function entitlements(plan) {
  return PLANS[plan] || PLANS.free;
}

export function can(user, feature) {
  return Boolean(entitlements(user && user.plan)[feature]);
}
