# Laya traverses the complete taxonomy hierarchically

Laya is AIMV's default decision provider. A move decision traverses three bounded choice
levels: all 16 Areas, all five to eight Categories in the selected Area, and all four Buckets in
the selected Category. The final choices include stable Bucket IDs and readable folder
routes. This makes every one of the 332 Buckets reachable without relying on retrieval
recall or exceeding Laya's 32-option schema limit.

Laya does typed classification rather than free-form generation. AIMV therefore keeps
the original basename and extracts the subject year/month locally. Users who need model
generated names can opt into the generative provider, which uses local candidate
retrieval and the same validated Classification Decision contract.

Local and Jev-compatible HTTP transports implement the same Decision Path. Parallel
files may classify concurrently; filesystem commits remain serialized.
