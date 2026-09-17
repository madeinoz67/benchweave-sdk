# Security Policy

The BenchWeave SDK is **pre-1.0** software maintained by a single person. This
policy is written to be honest about that rather than to promise more than it can
deliver.

## Reporting a vulnerability

**Please report privately, not in a public issue.**

Use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/madeinoz67/benchweave-sdk/security/advisories/new).
It creates a private advisory only you and the maintainer can see, and it handles
coordinated disclosure and CVE requests if it gets that far.

If you can, include:

- The SDK version or commit you tested
- Which surface is affected — the plugin contract packages, the Python runtime
  support, or the preview server used to develop plugins against recorded
  gateway sessions
- What an attacker gains, and what access they need to start
- The smallest reproduction you can manage

Reports are acknowledged and worked on a **best-effort** basis. No response time is
promised that cannot be honored. If something is being actively exploited, say so in
the report and it will be treated accordingly.

Please give a reasonable chance to ship a fix before disclosing publicly. Credit in
the advisory is gladly given — say how you want to be credited, or that you would
rather not be.

## Scope

**Supported version: the latest release.** The SDK is pre-1.0 and fixes are not
backported to older tags.

In scope — anything that lets a plugin or a crafted input exceed the boundary the
SDK is supposed to enforce:

- The plugin contract the SDK implements, where a defect lets a plugin exceed
  the boundary a conforming gateway enforces
- The preview server — anything that lets a recorded session or a crafted
  replay read or write outside its working directory
- Secrets or tokens leaking through logs, errors, or preview-server responses

Out of scope:

- Anything that requires an attacker to already have filesystem or OS-level
  access to the host — the SDK is local development tooling for single-operator
  use and does not defend against a compromised machine.
- Missing TLS or hardening headers. The preview server binds to loopback
  (`127.0.0.1`) by default and ships no TLS. If you rebind it, transport
  security is yours to provide.
- Denial of service through sheer volume against a server you control.
- Findings from automated scanners with no demonstrated impact.

## Known weaknesses

The SDK is pre-1.0 and has rough edges already known about; some are tracked as
public issues. If you find something already tracked, a comment on that issue is
more useful than a new report — but if you think it is more severe than it was
rated, say so privately. Re-rating severity beats defending it.
