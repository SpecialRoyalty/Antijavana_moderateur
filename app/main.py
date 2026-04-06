import os
from fastapi import FastAPI
from .db import Base, engine

app = FastAPI()

@app.on_event("startup")
def startup():
    print("STARTUP OK", flush=True)
    print("DATABASE_URL =", os.getenv("DATABASE_URL"), flush=True)
    print("CWD =", os.getcwd(), flush=True)
    Base.metadata.create_all(bind=engine)
    print("TABLES CREATED", flush=True)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Second bot is running"}
