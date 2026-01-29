"""
CSV Bulk Importer for AI Tools
Reads a CSV file and ingests tools using the existing ingest_tool() function
"""
import csv
import sys
from app import app
from ingestion import ingest_tool

def parse_tags(tags_string):
    """
    Parse tags from CSV string to list
    Supports comma-separated or semicolon-separated tags
    """
    if not tags_string or tags_string.strip() == "":
        return []
    
    # Try comma separation first
    if "," in tags_string:
        return [tag.strip() for tag in tags_string.split(",") if tag.strip()]
    # Try semicolon separation
    elif ";" in tags_string:
        return [tag.strip() for tag in tags_string.split(";") if tag.strip()]
    # Single tag
    else:
        return [tags_string.strip()]

def import_from_csv(csv_file_path):
    """
    Import tools from CSV file
    
    CSV Format:
    name,website,short_description,description,category,pricing,logo,tags
    """
    print("=" * 70)
    print("CSV BULK IMPORTER")
    print("=" * 70)
    print(f"\nReading CSV file: {csv_file_path}\n")
    
    success_count = 0
    error_count = 0
    duplicate_count = 0
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Validate CSV headers
            required_fields = ['name', 'website']
            if not all(field in reader.fieldnames for field in required_fields):
                print(f"❌ ERROR: CSV must contain at least: {', '.join(required_fields)}")
                print(f"   Found columns: {', '.join(reader.fieldnames)}")
                return
            
            print(f"✅ CSV columns validated: {', '.join(reader.fieldnames)}\n")
            print("-" * 70)
            
            # Process each row
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                tool_name = row.get('name', '').strip()
                
                if not tool_name:
                    print(f"Row {row_num}: ⚠️  SKIPPED - No name provided")
                    error_count += 1
                    continue
                
                # Build tool data dictionary
                tool_data = {
                    'name': tool_name,
                    'website': row.get('website', '').strip(),
                    'short_description': row.get('short_description', '').strip(),
                    'description': row.get('description', '').strip(),
                    'category': row.get('category', '').strip(),
                    'pricing': row.get('pricing', '').strip(),
                    'logo': row.get('logo', '').strip(),
                    'tags': parse_tags(row.get('tags', ''))
                }
                
                # Call ingest_tool function
                with app.app_context():
                    result, success = ingest_tool(tool_data)
                
                # Display result
                if success:
                    print(f"Row {row_num}: ✅ SUCCESS - {tool_name}")
                    success_count += 1
                else:
                    error_message = result.get('error', 'Unknown error')
                    if 'already exists' in error_message:
                        print(f"Row {row_num}: ⚠️  DUPLICATE - {tool_name}")
                        duplicate_count += 1
                    else:
                        print(f"Row {row_num}: ❌ ERROR - {tool_name} ({error_message})")
                        error_count += 1
    
    except FileNotFoundError:
        print(f"❌ ERROR: File not found: {csv_file_path}")
        return
    except Exception as e:
        print(f"❌ ERROR: Failed to process CSV: {e}")
        return
    
    # Summary
    print("-" * 70)
    print("\nIMPORT SUMMARY:")
    print(f"  ✅ Successfully imported: {success_count}")
    print(f"  ⚠️  Duplicates skipped:   {duplicate_count}")
    print(f"  ❌ Errors:               {error_count}")
    print(f"  📊 Total processed:      {success_count + duplicate_count + error_count}")
    print("\n" + "=" * 70)
    
    if success_count > 0:
        print("✅ CSV IMPORT COMPLETED SUCCESSFULLY")
    else:
        print("⚠️  CSV IMPORT COMPLETED WITH NO NEW TOOLS ADDED")
    print("=" * 70)

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python import_csv.py <csv_file_path>")
        print("\nExample:")
        print("  python import_csv.py tools.csv")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    import_from_csv(csv_file)

if __name__ == "__main__":
    main()
