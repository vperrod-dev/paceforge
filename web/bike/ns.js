// Browser storage is per-ORIGIN, and every PaceForge instance is served from the
// same host under a different base path (/paceforge, /pf/<name>, …). Suffixing
// each storage key with that base path keeps two portals open in one browser
// from overwriting each other's drafts, pending rides and tokens.
// Empty under node (selftests) — there is no location there and no sharing.
export const NS = typeof location === 'undefined'
  ? '' : '@' + (location.pathname.replace(/\/(index\.html)?$/, '') || '/');
