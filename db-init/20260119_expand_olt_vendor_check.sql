BEGIN;
ALTER TABLE olt DROP CONSTRAINT IF EXISTS olt_vendor_check;
ALTER TABLE olt ADD CONSTRAINT olt_vendor_check
  CHECK (vendor IN ('huawei','zyxel','zyxel1408A','zyxel2406','zyxel1240XA'));
COMMIT;
