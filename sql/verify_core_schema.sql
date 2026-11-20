-- Read-only checks for the Phase 1 core schema.

SELECT
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('sets', 'cards', 'price_history')
ORDER BY table_name, ordinal_position;

SELECT
    conrelid::regclass AS table_name,
    conname AS constraint_name,
    CASE contype
        WHEN 'p' THEN 'PRIMARY KEY'
        WHEN 'u' THEN 'UNIQUE'
        WHEN 'f' THEN 'FOREIGN KEY'
        WHEN 'c' THEN 'CHECK'
        ELSE contype::text
    END AS constraint_type,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
  AND conrelid IN ('sets'::regclass, 'cards'::regclass, 'price_history'::regclass)
ORDER BY 1, 3, 2;

SELECT
    tablename AS table_name,
    indexname AS index_name,
    indexdef AS definition
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('sets', 'cards', 'price_history')
ORDER BY table_name, index_name;

SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS referenced_table,
    ccu.column_name AS referenced_column,
    rc.update_rule,
    rc.delete_rule
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.constraint_schema = kcu.constraint_schema
JOIN information_schema.referential_constraints AS rc
  ON tc.constraint_name = rc.constraint_name
 AND tc.constraint_schema = rc.constraint_schema
JOIN information_schema.constraint_column_usage AS ccu
  ON rc.unique_constraint_name = ccu.constraint_name
 AND rc.unique_constraint_schema = ccu.constraint_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
  AND tc.table_name IN ('sets', 'cards', 'price_history')
ORDER BY tc.table_name, kcu.ordinal_position;

SELECT
    'sets' AS table_name,
    count(*) AS row_count
FROM sets
UNION ALL
SELECT
    'cards' AS table_name,
    count(*) AS row_count
FROM cards
UNION ALL
SELECT
    'price_history' AS table_name,
    count(*) AS row_count
FROM price_history
ORDER BY table_name;


