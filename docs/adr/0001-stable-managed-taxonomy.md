# Stable managed taxonomy with bounded provider choices

AIMV organizes files beneath a configurable dedicated Managed Root using stable Bucket
IDs and human-readable numbered paths. The bundled Taxonomy contains more than 200 leaf
Buckets, each described by hidden Folder Metadata. A typed decision provider receives
the bounded levels of the entire hierarchy and chooses stable IDs; it never supplies an arbitrary destination
path. This isolates managed files from existing personal folders, bounds decision size,
allows titles and paths to evolve without breaking identity, and makes path confinement
enforceable.

A typed provider traverses the entire Taxonomy hierarchically: every one of 16 Areas is offered,
followed by all five to eight Categories in the selected Area and all four Buckets in the
selected Category. Local Candidate Set retrieval is used only by the optional generative
fallback.
