BEGIN;

-- 1) Nueva columna materializada
ALTER TABLE ont
  ADD COLUMN IF NOT EXISTS pon_id TEXT;

-- 2) Función para derivar pon_id (vendor + vendor_ont_id)
CREATE OR REPLACE FUNCTION agis_derive_pon_id(vendor TEXT, vendor_ont_id TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
  v TEXT;
  s TEXT;
  a TEXT;
  b TEXT;
  c TEXT;
BEGIN
  IF vendor_ont_id IS NULL OR vendor_ont_id = '' THEN
    RETURN NULL;
  END IF;

  v := lower(coalesce(vendor,''));

  -- Huawei: CHASIS/SLOT/PON/ID_ONT  -> CHASIS/SLOT/PON
  IF position('/' in vendor_ont_id) > 0 THEN
    a := split_part(vendor_ont_id, '/', 1);
    b := split_part(vendor_ont_id, '/', 2);
    c := split_part(vendor_ont_id, '/', 3);
    IF a <> '' AND b <> '' AND c <> '' THEN
      RETURN a || '/' || b || '/' || c;
    END IF;
    RETURN NULL;
  END IF;

  -- Zyxel: quitar prefijo ont- si existe y trabajar con '-'
  s := regexp_replace(vendor_ont_id, '^ont-', '');

  a := split_part(s, '-', 1);
  b := split_part(s, '-', 2);
  c := split_part(s, '-', 3);

  -- zyxel2406 / 1240XA: SLOT-PON-ID -> SLOT-PON
  IF v IN ('zyxel2406','zyxel1240xa','zyxel_1240xa','1240xa') THEN
    IF a <> '' AND b <> '' THEN
      RETURN a || '-' || b;
    END IF;
    RETURN NULL;
  END IF;

  -- zyxel1408A: PON-ID -> PON
  IF v IN ('zyxel1408a','zyxel_1408a','1408a','zyxel') THEN
    IF a <> '' THEN
      RETURN a;
    END IF;
    RETURN NULL;
  END IF;

  -- fallback:
  -- si hay 3 tokens, asumimos SLOT-PON-ID -> SLOT-PON
  IF c <> '' THEN
    RETURN a || '-' || b;
  END IF;

  -- si hay 2 tokens, asumimos PON-ID -> PON
  IF b <> '' THEN
    RETURN a;
  END IF;

  -- si solo 1 token, devolverlo
  RETURN a;
END;
$$;


-- 3) Trigger: al insertar o cambiar vendor_ont_id / olt_id, recalcula pon_id
CREATE OR REPLACE FUNCTION ont_set_pon_id()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_vendor TEXT;
BEGIN
  SELECT vendor INTO v_vendor
  FROM olt
  WHERE id = NEW.olt_id;

  NEW.pon_id := agis_derive_pon_id(v_vendor, NEW.vendor_ont_id);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ont_set_pon_id ON ont;

CREATE TRIGGER trg_ont_set_pon_id
BEFORE INSERT OR UPDATE OF vendor_ont_id, olt_id
ON ont
FOR EACH ROW
EXECUTE FUNCTION ont_set_pon_id();


-- 4) Trigger opcional: si cambia el vendor de una OLT, recalcula PONs de sus ONTs
-- (puedes comentar esto si vendor no cambia nunca en producción)
CREATE OR REPLACE FUNCTION olt_recalc_pon_id_for_onts()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF lower(coalesce(NEW.vendor,'')) IS DISTINCT FROM lower(coalesce(OLD.vendor,'')) THEN
    UPDATE ont
       SET pon_id = agis_derive_pon_id(NEW.vendor, vendor_ont_id)
     WHERE olt_id = NEW.id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_olt_recalc_pon ON olt;

CREATE TRIGGER trg_olt_recalc_pon
AFTER UPDATE OF vendor
ON olt
FOR EACH ROW
EXECUTE FUNCTION olt_recalc_pon_id_for_onts();


-- 5) Backfill inicial
UPDATE ont o
SET pon_id = agis_derive_pon_id(ol.vendor, o.vendor_ont_id)
FROM olt ol
WHERE ol.id = o.olt_id
  AND (o.pon_id IS NULL OR o.pon_id = '');

COMMIT;
