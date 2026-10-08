// Backend (EBS) origins the extension may call (issue #164).
// package.sh replaces this file in the packaged ZIP with the origins given by
// --ebs-origin, so changing them needs a new extension version and a Twitch review.
// Empty here: unpackaged files only work in the local dev harness.
var EBS_ALLOWED_ORIGINS = [];
// Build stamp (issue #180): the version and origins package.sh built this file for,
// shown on the configuration page's Connection check.
var EXT_BUILD = {version: "dev", origins: []};
