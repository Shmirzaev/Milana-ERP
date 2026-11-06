# Training document generators

These are offline documentation tools, not application runtime code. From the
repository root, run the selected script with Python and its existing dependencies:

- generate_training_guide.py: legacy combined guide; retains output docs/Milana_ERP_Training_Guide.pdf.
- generate_training_pdfs.py: English department PDFs from docs/training/.
- generate_localized_training_pdfs.py: localized training PDF generation.
- translate_training_sources.py: translation workflow; imports the localized generator
  beside it and makes network requests. Run deliberately, not as a smoke test.

The latter tools retain docs/training/ sources and output/pdf/training/ destinations.
Relocation preserves their repository-root calculation. This cleanup validated
syntax, sibling imports and paths; it did not regenerate manuals or contact a translation service.
