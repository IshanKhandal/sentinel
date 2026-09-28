# Engineering Rules & Evidence-First Protocol

These rules are mandatory and apply to EVERY task in this project.

1. **NEVER assume** that a feature, API, endpoint, credential, dependency, dataset, camera, stream, model, library, environment variable, database table, or external service exists.

2. **NEVER invent:**
   - API endpoints
   - API responses
   - camera URLs
   - credentials
   - environment variables
   - database records
   - government data
   - live CCTV feeds
   - model accuracy
   - benchmark numbers
   - performance figures
   - cloud resources
   - external services
   - challenge requirements

3. **BEFORE implementing anything that depends on an external resource:**
   - inspect the repository
   - inspect existing configuration
   - inspect documentation available in the repository
   - inspect environment variables without exposing secrets
   - inspect installed dependencies
   - inspect existing API definitions
   - inspect available files
   - verify the resource actually exists

4. **If something cannot be verified: DO NOT GUESS.**
   Explicitly report:
   ```text
   UNKNOWN:
   <what is unknown>

   REQUIRED TO VERIFY:
   <what information is needed>

   BLOCKED BY:
   <why implementation cannot safely continue>
   ```

5. **NEVER silently replace a missing real dependency with fake data.**

6. **If DEMO/MOCK data is necessary for development:**
   - create an explicit DEMO mode
   - clearly label it
   - isolate it from production/live logic
   - never present demo data as real data
   - never claim a demo stream is live
   - never claim a mock API is a government API

7. **NEVER claim a feature is COMPLETE merely because:**
   - the UI exists
   - an endpoint returns 200
   - a button works
   - mock data appears
   - a simulated stream plays
   - a placeholder response exists

   A feature is COMPLETE only when the underlying functionality has been tested.

8. **Every important implementation claim must be backed by evidence.**
   - *Bad:* "RTSP ingestion is working."
   - *Good:* "RTSP ingestion was tested against <verified source>, connection succeeded, frames were decoded, and the test result is recorded in <file/log>."

9. **NEVER invent test results.**

10. **NEVER invent benchmark results.**

11. **NEVER claim scalability based only on theoretical assumptions.**
    Clearly separate:
    - `VERIFIED`
    - `IMPLEMENTED BUT UNBENCHMARKED`
    - `THEORETICAL`
    - `ASSUMED`
    - `UNKNOWN`

12. **When requirements conflict, DO NOT choose one silently.**
    Stop and report the conflict with the exact conflicting information.

13. **When documentation is ambiguous, do not interpret the ambiguity as permission to invent behavior.**

14. **When an external API is unavailable:**
    Do not fabricate a successful response. Implement an adapter/interface if useful and clearly mark the integration as `UNVERIFIED`/`BLOCKED`.

15. **When a library/API behaves differently than expected:**
    Inspect its actual documentation/types/source/package metadata before changing the implementation.

16. **Before modifying an existing feature:**
    Understand how the existing feature works. Do not replace working code merely because a different architecture seems cleaner.

17. **Preserve working functionality** unless there is a demonstrated reason to change it.

18. **Before deleting files, routes, APIs, database tables, components, or services:**
    Identify their consumers and dependencies. Never delete blindly.

19. **Before saying "done":**
    Run the relevant tests/build/lint/type checks and inspect the actual output.

20. **If a test fails:**
    Report the real failure. Do not hide it, suppress it, or mark it as passed.

21. **If a feature cannot be implemented because required information is missing:**
    STOP THAT PART. Continue only with independent work that does not require the missing information.

22. **Do not ask the user for information that can be verified from the repository, provided documentation, or available tools.**

23. **Do not pretend to have access to external systems that are not actually connected.**

24. **Never fabricate Sentinel/Gujarat Police requirements.**
    Treat the supplied Sentinel documentation/video as the source of truth for challenge-specific requirements.

25. **If information from the Sentinel website/documentation is not available or cannot be verified:**
    Explicitly say so.

26. **Maintain a REQUIREMENTS TRACEABILITY file:**
    [requirements-traceability.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/requirements-traceability.md)
    Every major requirement must contain:
    - Requirement
    - Source
    - Exact evidence
    - Implementation location
    - Verification method
    - Status (`VERIFIED` | `IMPLEMENTED` | `TESTED` | `PARTIAL` | `BLOCKED` | `UNKNOWN`)

27. **Maintain an ASSUMPTIONS file:**
    [assumptions.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/assumptions.md)
    Every assumption must be explicitly recorded. Do not allow undocumented assumptions to silently enter the system.

28. **Maintain an INTEGRATION STATUS file:**
    [integration-status.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/integration-status.md)
    For every external integration record:
    - Integration
    - Expected source
    - Verified?
    - Endpoint/resource
    - Authentication requirement
    - Current status
    - Evidence
    - Blockers

29. **Maintain a DEMO MODE document:**
    [demo-mode.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/demo-mode.md)
    Clearly document:
    - what is real
    - what is simulated
    - what data is synthetic
    - what streams are prerecorded
    - what APIs are mocked
    - what AI results are simulated

30. **Every UI component that displays potentially simulated information must have a trustworthy data-state:**
    `LIVE` | `DEMO` | `OFFLINE` | `UNKNOWN` | `UNAVAILABLE`

31. **NEVER display "LIVE" merely because the UI is running.**

32. **NEVER display "CONNECTED" unless the underlying connection has actually been established.**

33. **NEVER display "ONLINE" unless a verified health check supports it.**

34. **NEVER display "AI VERIFIED" unless the relevant inference actually ran.**

35. **NEVER display a watchlist match unless the backend actually performed the matching operation.**

36. **NEVER display a vehicle journey unless it was generated from actual stored observations.**

37. **NEVER invent geographic coordinates.**

38. **NEVER invent camera locations.**

39. **NEVER invent government camera metadata.**

40. **NEVER invent credentials.**

41. **NEVER expose secrets** in logs, UI, source code, commits, screenshots, or documentation.

42. **When uncertain, choose TRANSPARENCY over COMPLETENESS.**

43. **The correct response to missing information is:**
    "I don't have enough verified information to implement this safely."
    It is NOT: "I'll assume X."

### FINAL RULE
If there is a choice between:
- **A. an incomplete but truthful implementation**
- **B. a complete-looking implementation containing invented assumptions**

**ALWAYS choose A.**
