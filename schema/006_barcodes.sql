-- 006_barcodes.sql — barcodes that aren't ISBNs (decided 2026-11-23).
--
-- Older mass-market paperbacks and comics carry a UPC on the cover, and some game books a
-- store code (EAN-13 without a 978/979 prefix). Stored here, a scan of that code finds the
-- book. Kept as EAN-13 (a 12-digit UPC-A gets a leading 0) or EAN-8. Not unique: a cover
-- UPC can be shared by printings, so a scan may find more than one book.

ALTER TABLE books ADD COLUMN barcode TEXT
    CHECK (barcode IS NULL OR (length(barcode) IN (8, 13) AND barcode NOT GLOB '*[^0-9]*'));
CREATE INDEX books_barcode ON books (barcode) WHERE barcode IS NOT NULL;
