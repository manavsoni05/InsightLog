from sqlalchemy.orm import declarative_base

# All ORM models inherit from Base.
# Keeping Base in its own module prevents circular imports
# between session.py and individual model files.
Base = declarative_base()
