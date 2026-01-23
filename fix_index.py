from database import get_db_connection, create_vector_index

def fix():
    print("🔧 Attempting to fix Vector Index...")
    try:
        graph = get_db_connection()
        
        # 1. Drop existing if any (to fix dimensions mismatch possibility)
        try:
             # Try new syntax
             graph.query("DROP INDEX chunk_vector_index IF EXISTS")
             graph.query("DROP INDEX doc_embedding IF EXISTS")
             print("   - Dropped old indexes (chunk_vector_index, doc_embedding).")
        except Exception as e:
             print(f"   - Drop failed (might not exist): {e}")

        # 2. Recreate
        print("   - Creating new index (3072 dim)...")
        create_vector_index(graph, dimensions=3072)
        
        import time
        time.sleep(2)
        print("   - Verifying (Listing ALL indexes)...")
        res = graph.query("SHOW INDEXES YIELD name, type, state")
        found = False
        for r in res:
            print(f"     > Found: {r}")
            if r['name'] == 'chunk_vector_index':
                found = True
        
        if found:
             print(f"   ✅ SUCCESS! Index found.")
        else:
             print("   ❌ FAILURE! Index NOT found after creation.")
             
    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    fix()
