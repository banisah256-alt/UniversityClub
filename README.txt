
 UniversityClub.ipynb -> cells ko upar se neeche Run karein.


Bina notebook ke (terminal):
  pip install -r requirements.txt
  fastapi dev          # ya:  uvicorn main:app --reload
  -> http://127.0.0.1:8000

Local demo login:  Student@gmail.com / Student@123   |   Admin@gmail.com / Admin@123
Supabase mode me demo accounts nahi bante; admin .env ke ADMIN_IDENTIFIER / ADMIN_PASSWORD se banta hai.
Deploy:  fastapi deploy     (details notebook me)
