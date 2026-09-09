## 14. The streaming plugin registry was built, filled, and never given to the engine

**Class:** Bug · **Status:** Promoted (cleat-team/cleat#879, 2026-09-07)
**Upstream area:** none — found writing the first streaming-plugin coverage

Every streaming plugin call answered `no plugin stream registry configured`.
`WithPluginStreamRegistry` had seven references, all in `engine/unit_test.go`,
where the test supplies the option itself and so cannot see that nothing else
does. Same shape as cleat-team/cleat#769.
