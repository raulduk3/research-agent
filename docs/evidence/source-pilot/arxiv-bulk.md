# arXiv bulk data on S3: layout, terms and cost

Finding for #145, serving #66 (corpus release 2) and #146. Read on 2026-09-22 from the two primary pages named below. No bundle was downloaded.

## Sources read

- `https://info.arxiv.org/help/bulk_data_s3.html` (arXiv, "Full Text via S3")
- `https://info.arxiv.org/help/api/tou.html` (arXiv, "Terms of Use for arXiv APIs")

## Layout

- Bucket: `arxiv`, Amazon S3, requester pays: "the downloader pays Amazon for the download based on bandwidth used".
- PDF bundles: keys `pdf/arXiv_pdf_YYMM_###.tar`, about 500 MB each; manifest `pdf/arXiv_pdf_manifest.xml`.
- Source bundles: keys `src/arXiv_src_YYMM_###.tar`, about 500 MB each; manifest `src/arXiv_src_manifest.xml`.
- Size: "The complete set of files as of April 2025 is about 9.2 TB" (PDFs about 2.7 TB and source about 2.9 TB as of March 2023); growth "around 100 GB per month"; updated on "approximately monthly schedule".
- Bundles are grouped by the submission month in the key (`YYMM`), so a population drawn across a twelve-month window touches every bundle of those months. The bucket's region is not stated on the page; it is verified at first access and recorded here before any transfer.

## Terms

The bulk page directs readers to the API terms: "Please review the Terms of Use for arXiv APIs before using the arXiv bulk data buckets." The terms that bear on this project, quoted:

- Permitted: "Retrieve, store, transform, and share descriptive metadata about arXiv e-prints"; "Retrieve, store, and use the content of arXiv e-prints for your own personal use, or for research purposes"; "Direct users to arXiv.org to retrieve e-print content".
- Prohibited: "Store and serve arXiv e-prints (PDFs, source files, or other content) from your servers" without the copyright holder's permission; "Attempt to circumvent rate limits".
- Attribution: "If you build indexes or tools based on the full-text, you must link back to arXiv for downloads."
- Metadata: descriptive metadata is under CC0 1.0.
- Copyright: "E-prints remain subject to copyright protections held by authors or publishers, not arXiv." Most e-prints carry arXiv's non-exclusive distribution license, which grants distribution rights to arXiv, not to downstream users.
- Rate limit: the three-second, single-connection rule applies to the legacy APIs (OAI-PMH, RSS, arXiv API). The S3 bucket is not one of those APIs; no rate limit is stated for it.

## What this permits for the project

- Bulk retrieval of source and PDF bundles for research use: permitted ("for research purposes"), requester pays.
- In-region extraction with only extracted text, hashes and vectors leaving the region: consistent with the terms as read. Extracted text and vectors are derived artifacts held privately for research; nothing is served to anyone, and the private rating app shows card text and links back to arXiv for the paper itself (RD-14, IN-28).
- Retention: the same position as the API path recorded in `source-access.md` and `pilot-2026-09-21.md`: originals retained privately for research, never redistributed; the study's retention policy applies (Appendix A: Diagnostics, alerts and data handling).
- Not permitted: serving originals from the application host to anyone, including the raters. The app links to arXiv.

## Cost model, arithmetic from the page

- Requester-pays transfer out of AWS is priced by Amazon per gigabyte; reading the bucket from an instance in the same region is not charged as transfer out. The exact rates and the bucket's region are recorded at first access.
- A twelve-month window of source bundles is about 1.2 TB at the stated growth rate (source is roughly half of the monthly 100 GB). Reading that in-region and extracting text for a selected population leaves the bundles behind; only the extracted text (about 100 KB a paper) and vectors return home.

## Status

`arxiv_bulk_s3` is added to the permission registry as **allowed for research use with in-region processing; link-back required; no redistribution**. Blocked items before #146 runs: the bucket's region and the current per-gigabyte rates, both recorded on first access; and an AWS account with billing, which is the owner's.
