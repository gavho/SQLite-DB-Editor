import sqlite3

# --- ACTION REQUIRED: Replace this path with the correct one ---
# Example: "C:\\Flight Tracker\\test_flightlog.db"
db_path = "C:\\Flight Tracker\\test_flightlog.db"

conn = None # Initialize conn to None to prevent NameError

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Define the columns to check
    columns_to_fix = ['date', 'created_at', 'updated_at']

    # Iterate through the columns and update empty strings to NULL
    for column in columns_to_fix:
        print(f"Checking column '{column}' for empty strings...")
        cursor.execute(f"UPDATE missions SET {column} = NULL WHERE {column} = ''")

    # Commit the changes and close the connection
    conn.commit()
    print(f"Successfully replaced empty strings with NULL in columns: {', '.join(columns_to_fix)}")

except sqlite3.Error as e:
    print(f"An error occurred: {e}")
finally:
    if conn:
        conn.close()