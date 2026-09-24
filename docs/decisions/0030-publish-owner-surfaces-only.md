# 0030. Publish the owner surfaces only, through one ingress

- Status: accepted
- Date: 2026-09-24
- Issue: #336
- Spec: SDD Appendix A (Runtime and ownership: service roles; Hosts, isolation, recovery and spend: the public listener clause, the limits table and the batch memory thresholds); TDD-2.1.32. PL-22, SR-13 and TDD-2.1.47 are unchanged.
- Pull requests: pending

## Context

The owner needs to reach the platform from away from the development Mac,
and the platform's services should run inside the Lima guest's Compose stack
rather than on the Mac itself. Appendix A said there is no public listener,
and PL-22 and SR-13 keep the rating app on a private network with no route
from the internet. Those clauses protect the two raters. The owner surfaces
(the owner actions app, the inspector and their `/api/v1/` reads) already
require an owner session on every route, but nothing could publish them.

The same appendix declared per-role limits that `deploy/compose.yaml` did
not carry, and the batch memory thresholds (48 and 40 GiB) were sized to the
Mac's memory, not to the guest the services actually run in.

## Decision

- One ingress service, Caddy pinned by digest, is the only Compose service
  with a published port. It binds the guest's loopback, the guest forwards
  that one port to the host's loopback, and `bin/serve-public --provider
  ngrok` runs one tunnel client toward it. The tunnel terminates TLS; the
  ingress does not.
- The ingress proxies to the owner app alone (`platform/ingress.py#ROUTES`).
  `PUBLISHABLE_ROLES` names the roles whose every route requires an owner
  session, and today that is the owner app alone. `verify_published` reads
  the upstreams out of the committed Caddyfile and refuses any other role,
  so `bin/serve-public` will not start a tunnel in front of an edited
  Caddyfile that reaches the rating app or an internal service.
- The rating app is never routed publicly. PL-22 and SR-13 keep their text
  and tests. Raters reach the app on the host or over the owner's private
  network. Remote rating would need its own decision with its own consent
  record.
- The Appendix A clause is narrowed, not removed: there is no public
  listener for the rating app, storage, models, tools or any internal route.
  The owner surfaces may be published through the authenticated tunnel whose
  public hostname the profile records (`host.public_hostname`). The tunnel
  refuses to start unless `NGROK_DOMAIN` equals that hostname.
- The tunnel token and domain come from the environment (`NGROK_AUTHTOKEN`,
  `NGROK_DOMAIN`), never from a flag or a committed file, and the token never
  reaches the client's command line.
- The owner API admits cross-origin requests from exactly one front-end
  origin, the profile's `host.front_end_origin`. Requests must be
  credentialed, and no wildcard is allowed. The default is empty, which
  admits no origin.
- Every Compose service carries its Appendix A vCPU and memory limit. The
  table gains an owner app row (0.5 / 1 / 0) and an ingress row
  (1 / 0.5 / 0), and `ingress` joins the closed role vocabulary with layer
  infrastructure.
- The guest is sized from the profile (`host.guest_vcpus`,
  `host.guest_memory_gib`). The batch thresholds are three quarters and five
  eighths of the guest's memory, which keeps 48 and 40 GiB for a 64 GiB
  guest.

## Consequences

- A request from the internet reaches the owner app's login page or a 401,
  never data. The rating app, storage, models and tools have no public
  route, and a test proves the rating app is absent from the published set.
- The tunnel client's outbound connection to the tunnel provider is a new
  host-side path. It runs on the Mac, outside the guest's egress rules, under
  the operator's authority, as provisioning tools do. No application
  container reaches the provider.
- Serving the compose `app` service as the rating launcher and the `owner`
  service as the owner launcher replaces the old `serve-app` command, which
  had no launcher.
- The per-role limits add up to more than the default 8 GiB guest. They are
  ceilings, not reservations, as Appendix A already said. The measured floor
  amendment before #74 still resizes them.
- The tunnel's public hostname is a deployment binding kept in the private
  profile. The committed example leaves it empty, so no tunnel can start from
  the committed files alone.
