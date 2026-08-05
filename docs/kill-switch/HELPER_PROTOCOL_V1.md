# Kill Switch Helper Protocol v1

This document defines the stable machine-readable boundary between the future
PIA Bazzite application client and the privileged helper.

Stage 2D.2 still does **not** enable host-network operation. The helper still refuses
the initial network namespace and still manages only the isolated stage-1 test
table. This stage standardizes requests, responses, and error handling before
production rules are introduced.

## Request actions

Protocol v1 currently exposes only these fixed actions:

- `status`
- `enable`
- `set-interfaces`
- `set-endpoints`
- `add-endpoint`
- `remove-endpoint`
- `disable`
- `emergency-reset`

The helper does not accept arbitrary commands, table names, chain names,
executable paths, or nftables fragments.

## Response envelope

Every successful JSON response contains:

- `ok: true`
- `schema_version: 1`
- `protocol_version: 1`
- `helper_stage`
- `action`

Every error JSON response contains:

- `ok: false`
- `schema_version: 1`
- `protocol_version: 1`
- `helper_stage`
- `action`
- `error`
- `message`

Unknown or malformed action text is reported as `action: "unknown"`; arbitrary
input is never copied into the action field.

## Deterministic command-line failures

Missing arguments, unknown actions, validation failures, privilege failures,
safety-boundary failures, nftables failures, and installation-boundary failures
all produce one JSON object on standard error and a non-zero exit status.

This is required so the GUI can distinguish user cancellation, malformed
requests, unavailable helper installation, nftables failures, and structural
verification errors without parsing human-readable terminal text.

## Safety status

This protocol milestone is exercised by isolated namespace tests only. It does not:

- remove the host-namespace refusal;
- install a persistent helper;
- add a custom Polkit policy;
- modify NetworkManager;
- activate a real host kill switch;
- connect the GUI to the helper.
