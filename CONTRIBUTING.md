# Contributing to CalibAgent

CalibAgent accepts contributions only when their provenance and licensing are
clear. This protects the reproducibility record and the rights of authors,
contributors, data providers, and third parties.

## Rights and inbound license

By submitting a contribution, you certify that you have the right to submit it
and agree that it is licensed under the license assigned to that file type in
[`LICENSE_SCOPE.md`](LICENSE_SCOPE.md). Copyright is not assigned to the
project; contributors retain copyright in their original contributions.

Every human-submitted contribution commit must include a Developer
Certificate of Origin sign-off:

```text
Signed-off-by: Your Legal Name <your-email@example.com>
```

Create it with `git commit -s`. The sign-off certifies the contribution under
the [Developer Certificate of Origin 1.1](https://developercertificate.org/).
It is a provenance certification, not a copyright transfer.

Automated maintenance commits must identify the automation account and must
not impersonate a human signatory. A human who later submits or adopts
automated output is responsible for reviewing its provenance and rights.

## Required checks

Before opening a pull request:

1. identify any third-party code, data, media, model, checkpoint, or generated
   asset and include its source and license;
2. do not submit confidential information, credentials, personal data, robot
   recordings lacking authorization, or material restricted by an employer,
   university, sponsor, or publisher;
3. preserve experiment manifests, hashes, negative results, and claim
   boundaries;
4. run the repository quality and publication-audit checks described in the
   README;
5. sign every contribution commit.

AI assistance does not remove the contributor's responsibility to inspect the
output, establish that it may be submitted, and make the human technical and
expressive decisions represented by the contribution. Do not identify an AI
system as a copyright owner or scholarly author.

## Scholarly credit

Source-code contribution, copyright ownership, repository acknowledgment, and
paper authorship are distinct. Contributions are recorded in Git history.
Paper authorship and author order are determined separately from material
intellectual contribution and accountability; they are not automatically
created by a pull request.

Until a project-paper DOI is available, cite the exact software release or
commit using [`CITATION.cff`](CITATION.cff).
