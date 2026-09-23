# Pinned model and provider sources

Checked 2026-09-20, except where noted. These are the primary sources behind the model and provider choices pinned in SDD Appendix A: Launch profile and the Jev rubric in SDD 6.3. Public metadata and documentation establish candidates and interface descriptions, not successful local execution. Pinned revisions were read from the public model metadata API without downloading weights.

- Embedding model: [modernbert-embed-base model card](https://huggingface.co/nomic-ai/modernbert-embed-base), checked 2026-09-21.
- Agent model: `glm-5.3-flash` served per-token by Z.ai's first-party API, the one named provider under launch profile v2 (decision 0015); its model card and API documentation are the provider's own pages, checked 2026-09-22 on #129. The earlier candidate, [GLM-4.6V-FP8 model card](https://huggingface.co/zai-org/GLM-4.6V-FP8) with [vLLM](https://docs.vllm.ai/en/latest/models/supported_models/) serving, is superseded and kept for the record.
- Jev Choice and confidence interfaces: [Primitives](https://docs.typesafe.ai/primitives) and [Confidence](https://docs.typesafe.ai/confidence).
- Jev provider access, interface, identity semantics and operating values, read from the live service through the ngrok AI gateway on 2026-09-22: [jev-provider.md](jev-provider.md). Retention permission remains unestablished.

Provider access, limits, retention permission and operating values are not established by these pages. They are the readiness gates of SDD RD-24 and are tracked in #59 and #100.
