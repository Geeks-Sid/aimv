# OpenRouter Jev is the default typed decision provider

AIMV uses OpenRouter's hosted Decisions API with `typesafe/jev-1.13` by default. Jev
receives the same complete Area → Category → Bucket Decision Path previously designed
for Laya. Its `state`, `questions`, `instructions`, and per-option `criteria` contract
preserves readable folder descriptions while returning typed choices and probabilities.

The hosted provider avoids local model downloads and hardware-specific PyTorch
constraints. Laya remains available for users who need open weights, local inference, or
self-hosting. The generative fallback remains available when prose generation or image
understanding is required.

OpenRouter authentication is supplied only through `OPENROUTER_API_KEY`; the model never
receives the credential. Filesystem destinations are still resolved from stable Bucket
IDs locally, and commits remain serialized.
