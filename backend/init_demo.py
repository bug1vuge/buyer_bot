from app.main import engine, SessionLocal
from app.models import Base, Product
Base.metadata.create_all(bind=engine)
session = SessionLocal()
p = Product(title="Духи Шанель", base_price_cents=800000)  # 8000.00 руб
session.add(p)
session.commit()
print("Product created id:", p.id)
session.close()
