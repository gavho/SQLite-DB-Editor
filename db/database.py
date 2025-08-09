from sqlalchemy import create_engine
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session


def get_session_and_models(db_path):
    """
    Creates an SQLAlchemy engine, reflects the database schema,
    and returns a session and the dynamically created models.
    """
    try:
        engine = create_engine(f"sqlite:///{db_path}")

        # Use the automap extension to reflect the database schema
        Base = automap_base()
        Base.prepare(autoload_with=engine)

        # Now, Base.classes contains the dynamically created models
        # for each table in your database.
        print("Models successfully reflected from the database.")

        # Create a session to interact with the database
        Session_maker = Session(engine)

        return Session_maker, Base.classes

    except Exception as e:
        print(f"Error loading database schema: {e}")
        return None, None