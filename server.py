from fastapi import FastAPI, APIRouter, HTTPException, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timedelta
import random
import base64
import litellm
from litellm import acompletion
import stripe
import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')  # For Render deployment
STRIPE_API_KEY = os.environ.get('STRIPE_API_KEY')
GOOGLE_CLIENT_ID = '181639765177-3tnbuada63aokj13vpjr7m2lh5bvvqpb.apps.googleusercontent.com'
JWT_SECRET = os.environ.get('JWT_SECRET', 'arcana-secret-key-change-in-production')

# Configure Stripe
stripe.api_key = STRIPE_API_KEY

# Configure litellm - use OpenAI key if available, otherwise Emergent key
LLM_API_KEY = OPENAI_API_KEY or EMERGENT_LLM_KEY

# Pydantic models for Stripe responses
class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str

class CheckoutStatusResponse(BaseModel):
    status: str
    payment_status: str

# Tarot card data - 78 cards (22 Major Arcana + 56 Minor Arcana)
TAROT_CARDS_DE = [
    # Major Arcana (0-21)
    {"card_id": 0, "name_de": "Der Narr", "arcana_type": "major", "keywords_de": "Neuanfang, Spontanität, Unschuld"},
    {"card_id": 1, "name_de": "Der Magier", "arcana_type": "major", "keywords_de": "Willenskraft, Manifestation, Schöpferkraft"},
    {"card_id": 2, "name_de": "Die Hohepriesterin", "arcana_type": "major", "keywords_de": "Intuition, Geheimnis, inneres Wissen"},
    {"card_id": 3, "name_de": "Die Herrscherin", "arcana_type": "major", "keywords_de": "Fülle, Weiblichkeit, Natur"},
    {"card_id": 4, "name_de": "Der Herrscher", "arcana_type": "major", "keywords_de": "Autorität, Struktur, Kontrolle"},
    {"card_id": 5, "name_de": "Der Hierophant", "arcana_type": "major", "keywords_de": "Tradition, Konformität, Spiritualität"},
    {"card_id": 6, "name_de": "Die Liebenden", "arcana_type": "major", "keywords_de": "Liebe, Harmonie, Entscheidungen"},
    {"card_id": 7, "name_de": "Der Wagen", "arcana_type": "major", "keywords_de": "Willenskraft, Sieg, Entschlossenheit"},
    {"card_id": 8, "name_de": "Die Kraft", "arcana_type": "major", "keywords_de": "Mut, innere Stärke, Geduld"},
    {"card_id": 9, "name_de": "Der Eremit", "arcana_type": "major", "keywords_de": "Innenschau, Einsamkeit, Weisheit"},
    {"card_id": 10, "name_de": "Das Rad des Schicksals", "arcana_type": "major", "keywords_de": "Schicksal, Zyklen, Wandel"},
    {"card_id": 11, "name_de": "Die Gerechtigkeit", "arcana_type": "major", "keywords_de": "Gerechtigkeit, Wahrheit, Karma"},
    {"card_id": 12, "name_de": "Der Gehängte", "arcana_type": "major", "keywords_de": "Loslassen, Opfer, neue Perspektive"},
    {"card_id": 13, "name_de": "Der Tod", "arcana_type": "major", "keywords_de": "Transformation, Ende, Neuanfang"},
    {"card_id": 14, "name_de": "Die Mäßigkeit", "arcana_type": "major", "keywords_de": "Balance, Harmonie, Geduld"},
    {"card_id": 15, "name_de": "Der Teufel", "arcana_type": "major", "keywords_de": "Versuchung, Abhängigkeit, Schatten"},
    {"card_id": 16, "name_de": "Der Turm", "arcana_type": "major", "keywords_de": "Zerstörung, Chaos, Offenbarung"},
    {"card_id": 17, "name_de": "Der Stern", "arcana_type": "major", "keywords_de": "Hoffnung, Inspiration, Heilung"},
    {"card_id": 18, "name_de": "Der Mond", "arcana_type": "major", "keywords_de": "Illusion, Unterbewusstsein, Intuition"},
    {"card_id": 19, "name_de": "Die Sonne", "arcana_type": "major", "keywords_de": "Freude, Erfolg, Vitalität"},
    {"card_id": 20, "name_de": "Das Gericht", "arcana_type": "major", "keywords_de": "Erwachen, Erneuerung, Urteil"},
    {"card_id": 21, "name_de": "Die Welt", "arcana_type": "major", "keywords_de": "Vollendung, Erfüllung, Erfolg"},
    
    # Minor Arcana - Stäbe/Wands (22-35) - Feuer, Energie, Kreativität
    {"card_id": 22, "name_de": "Ass der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Neue Ideen, Inspiration, Potenzial"},
    {"card_id": 23, "name_de": "Zwei der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Planung, Zukunft, Entdeckung"},
    {"card_id": 24, "name_de": "Drei der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Expansion, Voraussicht, Weitblick"},
    {"card_id": 25, "name_de": "Vier der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Feier, Harmonie, Heimkehr"},
    {"card_id": 26, "name_de": "Fünf der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Konflikt, Wettbewerb, Spannung"},
    {"card_id": 27, "name_de": "Sechs der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Sieg, Anerkennung, Fortschritt"},
    {"card_id": 28, "name_de": "Sieben der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Verteidigung, Beharrlichkeit, Herausforderung"},
    {"card_id": 29, "name_de": "Acht der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Schnelligkeit, Bewegung, Handlung"},
    {"card_id": 30, "name_de": "Neun der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Ausdauer, Durchhaltevermögen, Resilienz"},
    {"card_id": 31, "name_de": "Zehn der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Belastung, Verantwortung, Bürde"},
    {"card_id": 32, "name_de": "Bube der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Begeisterung, Abenteuerlust, Neugierde"},
    {"card_id": 33, "name_de": "Ritter der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Leidenschaft, Impulsivität, Abenteuer"},
    {"card_id": 34, "name_de": "Königin der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Charisma, Selbstbewusstsein, Unabhängigkeit"},
    {"card_id": 35, "name_de": "König der Stäbe", "arcana_type": "minor", "suit": "wands", "keywords_de": "Vision, Führung, Unternehmertum"},
    
    # Minor Arcana - Kelche/Cups (36-49) - Wasser, Emotionen, Beziehungen
    {"card_id": 36, "name_de": "Ass der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Liebe, Intuition, Neuanfang"},
    {"card_id": 37, "name_de": "Zwei der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Partnerschaft, Verbindung, Harmonie"},
    {"card_id": 38, "name_de": "Drei der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Freundschaft, Gemeinschaft, Freude"},
    {"card_id": 39, "name_de": "Vier der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Meditation, Rückzug, Unzufriedenheit"},
    {"card_id": 40, "name_de": "Fünf der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Verlust, Trauer, Enttäuschung"},
    {"card_id": 41, "name_de": "Sechs der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Nostalgie, Kindheitserinnerungen, Unschuld"},
    {"card_id": 42, "name_de": "Sieben der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Illusionen, Fantasie, Entscheidungen"},
    {"card_id": 43, "name_de": "Acht der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Loslassen, Weitergehen, Suche"},
    {"card_id": 44, "name_de": "Neun der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Zufriedenheit, Wünsche, Erfüllung"},
    {"card_id": 45, "name_de": "Zehn der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Glück, Familie, emotionale Erfüllung"},
    {"card_id": 46, "name_de": "Bube der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Träumer, Kreativität, Botschaften"},
    {"card_id": 47, "name_de": "Ritter der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Romantik, Charme, Ideale"},
    {"card_id": 48, "name_de": "Königin der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Mitgefühl, Intuition, Fürsorge"},
    {"card_id": 49, "name_de": "König der Kelche", "arcana_type": "minor", "suit": "cups", "keywords_de": "Emotionale Balance, Diplomatie, Weisheit"},
    
    # Minor Arcana - Schwerter/Swords (50-63) - Luft, Verstand, Konflikt
    {"card_id": 50, "name_de": "Ass der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Klarheit, Wahrheit, Durchbruch"},
    {"card_id": 51, "name_de": "Zwei der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Entscheidung, Blockade, Zwickmühle"},
    {"card_id": 52, "name_de": "Drei der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Herzschmerz, Trennung, Leid"},
    {"card_id": 53, "name_de": "Vier der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Ruhe, Erholung, Rückzug"},
    {"card_id": 54, "name_de": "Fünf der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Niederlage, Konflikt, Kompromiss"},
    {"card_id": 55, "name_de": "Sechs der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Übergang, Veränderung, Erleichterung"},
    {"card_id": 56, "name_de": "Sieben der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Täuschung, List, Strategie"},
    {"card_id": 57, "name_de": "Acht der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Gefangenschaft, Angst, Einschränkung"},
    {"card_id": 58, "name_de": "Neun der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Sorgen, Albträume, Angst"},
    {"card_id": 59, "name_de": "Zehn der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Ende, Verrat, Transformation"},
    {"card_id": 60, "name_de": "Bube der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Neugier, Wachsamkeit, Nachforschung"},
    {"card_id": 61, "name_de": "Ritter der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Entschlossenheit, Direktheit, Sturm"},
    {"card_id": 62, "name_de": "Königin der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Intellekt, Unabhängigkeit, Klarheit"},
    {"card_id": 63, "name_de": "König der Schwerter", "arcana_type": "minor", "suit": "swords", "keywords_de": "Autorität, Logik, Gerechtigkeit"},
    
    # Minor Arcana - Münzen/Pentacles (64-77) - Erde, Materie, Wohlstand
    {"card_id": 64, "name_de": "Ass der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Manifestation, Gelegenheit, Wohlstand"},
    {"card_id": 65, "name_de": "Zwei der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Balance, Anpassung, Zeitmanagement"},
    {"card_id": 66, "name_de": "Drei der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Teamwork, Zusammenarbeit, Können"},
    {"card_id": 67, "name_de": "Vier der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Sicherheit, Kontrolle, Besitz"},
    {"card_id": 68, "name_de": "Fünf der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Mangel, Isolation, Sorgen"},
    {"card_id": 69, "name_de": "Sechs der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Großzügigkeit, Geben, Empfangen"},
    {"card_id": 70, "name_de": "Sieben der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Geduld, Investition, Bewertung"},
    {"card_id": 71, "name_de": "Acht der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Handwerk, Fleiß, Meisterschaft"},
    {"card_id": 72, "name_de": "Neun der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Unabhängigkeit, Luxus, Selbstgenügsamkeit"},
    {"card_id": 73, "name_de": "Zehn der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Reichtum, Familie, Erbe"},
    {"card_id": 74, "name_de": "Bube der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Lernbereitschaft, Praktikabilität, Ziele"},
    {"card_id": 75, "name_de": "Ritter der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Verantwortung, Beständigkeit, Routine"},
    {"card_id": 76, "name_de": "Königin der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Fürsorglichkeit, Praktikabilität, Wohlstand"},
    {"card_id": 77, "name_de": "König der Münzen", "arcana_type": "minor", "suit": "pentacles", "keywords_de": "Überfluss, Sicherheit, Erfolg"},
]

# Models
class DeviceInit(BaseModel):
    device_id: str

class DeviceStatus(BaseModel):
    device_id: str
    cards_drawn_today: int
    remaining_free_cards: int
    is_premium: bool
    last_reset_date: str

class CardDraw(BaseModel):
    device_id: str
    user_question: Optional[str] = None  # "Frage des Tages"
    life_situation: Optional[str] = None  # "Lebenssituation"

class CardResponse(BaseModel):
    card_id: int
    name_de: str
    arcana_type: str
    keywords_de: str
    image_base64: Optional[str] = None

class InterpretationRequest(BaseModel):
    device_id: str
    card_id: int
    card_name: str
    user_question: Optional[str] = None  # "Frage des Tages"
    life_situation: Optional[str] = None  # "Lebenssituation"

class InterpretationResponse(BaseModel):
    interpretation: str

class CheckoutRequest(BaseModel):
    device_id: str
    origin_url: str

class SubscriptionStatus(BaseModel):
    is_premium: bool
    subscription_id: Optional[str] = None
    status: Optional[str] = None

class IAPVerifyRequest(BaseModel):
    device_id: str
    receipt: str
    product_id: str
    transaction_id: str

class IAPVerifyResponse(BaseModel):
    success: bool
    is_premium: bool
    message: str

# New Models for Journal/History Features
class ReadingNote(BaseModel):
    device_id: str
    reading_id: str
    note: str

class ReadingHistory(BaseModel):
    reading_id: str
    card_id: int
    card_name: str
    interpretation: str
    note: Optional[str] = None
    created_at: str
    spread_type: str = "single"
    spread_position: Optional[str] = None

class HistoryResponse(BaseModel):
    readings: List[ReadingHistory]
    total_count: int

class MultiCardDrawRequest(BaseModel):
    device_id: str
    spread_type: str = "single"  # "single", "three_card", "past_present_future"

class MultiCardResponse(BaseModel):
    spread_type: str
    cards: List[CardResponse]
    positions: List[str]

# Helper functions
async def get_or_create_device(device_id: str):
    """Get or create a device record"""
    device = await db.devices.find_one({"device_id": device_id})
    
    if not device:
        device = {
            "device_id": device_id,
            "cards_drawn_today": [],
            "last_reset_date": datetime.utcnow().date().isoformat(),
            "is_premium": False,
            "subscription_id": None,
            "created_at": datetime.utcnow()
        }
        await db.devices.insert_one(device)
    else:
        # Check if we need to reset the daily counter
        last_reset = datetime.fromisoformat(device["last_reset_date"]).date()
        today = datetime.utcnow().date()
        
        if last_reset < today:
            await db.devices.update_one(
                {"device_id": device_id},
                {
                    "$set": {
                        "cards_drawn_today": [],
                        "last_reset_date": today.isoformat()
                    }
                }
            )
            device["cards_drawn_today"] = []
            device["last_reset_date"] = today.isoformat()
    
    return device

async def generate_card_image(card_name: str, keywords: str) -> str:
    """Generate a mystical tarot card image using Gemini"""
    try:
        # Use litellm with Gemini for image generation
        # Note: For production, you may want to use a dedicated image generation API
        prompt = f"Erstelle ein mystisches, dunkles Tarot-Karten-Bild für '{card_name}'. Schlüsselworte: {keywords}. Der Stil sollte dunkel, geheimnisvoll und spirituell sein mit goldenen und violetten Akzenten. Keine Texte auf dem Bild."
        
        # For now, return None as image generation requires special setup
        # The app will use fallback placeholder images
        logger.info(f"Image generation requested for: {card_name}")
        return None
    except Exception as e:
        logger.error(f"Error generating card image: {e}")
        return None

def get_moon_phase_info() -> dict:
    """Calculate current moon phase and return mystical info"""
    import math
    
    now = datetime.utcnow()
    known_new_moon = datetime(2000, 1, 6, 18, 14, 0)
    diff = (now - known_new_moon).total_seconds()
    days = diff / (60 * 60 * 24)
    synodic_month = 29.53059
    lunar_age = (days % synodic_month) / synodic_month
    illumination = round((1 - math.cos(lunar_age * 2 * math.pi)) / 2 * 100)
    
    phases = [
        (0.0625, "new_moon", "🌑", "Neumond", "Eine Zeit des Neubeginns und der inneren Einkehr.", "Deine Karte spricht heute von verborgenen Möglichkeiten und frischen Starts."),
        (0.1875, "waxing_crescent", "🌒", "Zunehmende Sichel", "Hoffnung keimt auf, Pläne nehmen Form an.", "Deine Karte zeigt heute Wege, wie du deine Absichten manifestieren kannst."),
        (0.3125, "first_quarter", "🌓", "Erstes Viertel", "Zeit für Entscheidungen und erste Schritte.", "Deine Karte fordert dich heute auf, mutig voranzuschreiten."),
        (0.4375, "waxing_gibbous", "🌔", "Zunehmender Mond", "Energie baut sich auf, Dinge kommen in Bewegung.", "Deine Karte verstärkt heute ihre Botschaft – höre genau hin."),
        (0.5625, "full_moon", "🌕", "Vollmond", "Höhepunkt der Energie, Klarheit und Erleuchtung.", "Deine Karte offenbart heute ihre tiefste Wahrheit mit voller Kraft."),
        (0.6875, "waning_gibbous", "🌖", "Abnehmender Mond", "Zeit der Dankbarkeit und des Teilens.", "Deine Karte erinnert dich heute daran, was du bereits erreicht hast."),
        (0.8125, "last_quarter", "🌗", "Letztes Viertel", "Loslassen und Raum schaffen für Neues.", "Deine Karte weist heute auf das hin, was du freigeben darfst."),
        (0.9375, "waning_crescent", "🌘", "Abnehmende Sichel", "Ruhe vor dem Neubeginn, innere Reflexion.", "Deine Karte spricht heute zu deinem Unterbewusstsein."),
        (1.0, "new_moon", "🌑", "Neumond", "Eine Zeit des Neubeginns und der inneren Einkehr.", "Deine Karte spricht heute von verborgenen Möglichkeiten und frischen Starts."),
    ]
    
    for threshold, phase, emoji, name_de, description, influence in phases:
        if lunar_age < threshold:
            return {
                "phase": phase,
                "emoji": emoji,
                "name_de": name_de,
                "description_de": description,
                "influence_de": influence,
                "illumination": illumination
            }
    
    return phases[0][1:]  # Default to new moon

async def generate_interpretation(card_name: str, keywords: str, include_moon: bool = True, user_question: str = None, life_situation: str = None) -> str:
    """Generate a practical interpretation using OpenAI GPT with moon phase context and personalization"""
    try:
        moon_info = get_moon_phase_info()
        
        moon_context = ""
        if include_moon:
            moon_context = f"\n\nAktueller Mondzyklus: {moon_info['name_de']} ({moon_info['illumination']}% beleuchtet)"
        
        # Personalisierter Kontext
        personal_context = ""
        if user_question or life_situation:
            personal_context = "\n\n--- PERSÖNLICHER KONTEXT ---"
            if user_question:
                personal_context += f"\nFrage des Suchenden: {user_question}"
            if life_situation:
                personal_context += f"\nAktuelle Lebenssituation: {life_situation}"
            personal_context += "\n--- ENDE PERSÖNLICHER KONTEXT ---"
        
        base_instruction = f"""Erstelle eine KONKRETE, PRAKTISCHE Deutung für die Tarot-Karte '{card_name}' mit den Schlüsselworten: {keywords}.{moon_context}{personal_context}

Die Deutung sollte:
- 100-150 Worte lang sein
- KONKRET und PRAKTISCH sein (keine vagen Philosophien!)
- Den Suchenden direkt ansprechen (Du/Dich)
- 2-3 konkrete Handlungsempfehlungen geben
- Bezug zum ALLTAG haben (Arbeit, Beziehungen, Entscheidungen)
- Auf Deutsch verfasst sein
- Kurz die Mondphase erwähnen und was sie bedeutet"""

        if user_question or life_situation:
            base_instruction += """
- WICHTIG: Beziehe die Deutung DIREKT auf die Frage und Lebenssituation des Suchenden!
- Gib konkrete Hinweise, die zur persönlichen Situation passen"""
        
        base_instruction += """

Beispiel-Struktur:
1. Ein Satz zur Mondphase
2. Was die Karte für HEUTE bedeutet (und falls vorhanden: Bezug zur Frage/Situation)
3. Konkrete Handlungsempfehlung
4. Worauf du achten solltest"""
        
        # Use litellm for text generation
        response = await acompletion(
            model="openai/gpt-4o",
            messages=[
                {"role": "system", "content": "Du bist ein erfahrener Tarot-Berater. Deine Deutungen sind KONKRET, PRAKTISCH und ALLTAGSBEZOGEN. Du gibst klare Hinweise und Handlungsempfehlungen. Vermeide zu viel Philosophie - sei direkt und hilfreich."},
                {"role": "user", "content": base_instruction}
            ],
            api_key=LLM_API_KEY
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating interpretation: {e}")
        return "Die Karten flüstern heute leise. Versuche es erneut, wenn die Sterne günstiger stehen."

# Google Auth Models
class GoogleAuthRequest(BaseModel):
    credential: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    picture: Optional[str] = None

class AuthResponse(BaseModel):
    access_token: str
    user: UserResponse

# Google Auth Endpoints
@api_router.post("/auth/google", response_model=AuthResponse)
async def google_auth(request: GoogleAuthRequest):
    """Authenticate user with Google OAuth token"""
    try:
        # Verify the Google token
        idinfo = id_token.verify_oauth2_token(
            request.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        
        # Extract user information
        google_id = idinfo.get('sub')
        email = idinfo.get('email')
        name = idinfo.get('name', email.split('@')[0])
        picture = idinfo.get('picture', '')
        
        # Find or create user in database
        user = await db.users.find_one({"google_id": google_id})
        
        if not user:
            # Create new user
            user = {
                "google_id": google_id,
                "email": email,
                "name": name,
                "picture": picture,
                "created_at": datetime.utcnow(),
                "last_login": datetime.utcnow(),
                "is_premium": False,
                "subscription_id": None,
            }
            result = await db.users.insert_one(user)
            user["_id"] = result.inserted_id
            
            logger.info(f"New user created: {email}")
        else:
            # Update last login
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"last_login": datetime.utcnow(), "picture": picture}}
            )
            logger.info(f"User logged in: {email}")
        
        # Check if user has any devices linked and transfer their premium status
        # This allows users to keep their subscription when they login
        user_devices = await db.devices.find({"user_id": str(user["_id"])}).to_list(length=100)
        if not user_devices:
            # Check for premium devices without user_id that match email pattern
            # This is a migration path for existing users
            pass
        
        # Create JWT token
        token_data = {
            "sub": str(user["_id"]),
            "email": email,
            "exp": datetime.utcnow() + timedelta(days=30)
        }
        access_token = jwt.encode(token_data, JWT_SECRET, algorithm="HS256")
        
        return AuthResponse(
            access_token=access_token,
            user=UserResponse(
                id=str(user["_id"]),
                email=email,
                name=name,
                picture=picture
            )
        )
        
    except ValueError as e:
        logger.error(f"Invalid Google token: {e}")
        raise HTTPException(status_code=401, detail="Ungültiges Google-Token")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=500, detail="Authentifizierung fehlgeschlagen")

@api_router.post("/auth/link-device")
async def link_device_to_user(device_id: str, user_id: str):
    """Link a device to a user account - Sync premium status between user and device"""
    from bson import ObjectId
    
    try:
        logger.info(f"Linking device {device_id} to user {user_id}")
        
        # Get the device
        device = await db.devices.find_one({"device_id": device_id})
        if not device:
            device = await get_or_create_device(device_id)
        
        # Get user data
        user = None
        try:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
        except:
            pass
        
        # Link device to user FIRST
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"user_id": user_id}}
        )
        
        # BIDIRECTIONAL Premium Sync:
        # 1. If USER has premium -> Device gets premium
        # 2. If DEVICE has premium but USER doesn't -> User gets premium (payment was on this device)
        
        device_is_premium = device.get("is_premium", False)
        user_is_premium = user.get("is_premium", False) if user else False
        
        if user_is_premium:
            # User has premium - sync to device
            await db.devices.update_one(
                {"device_id": device_id},
                {"$set": {
                    "is_premium": True, 
                    "subscription_id": user.get("subscription_id"),
                    "stripe_customer_id": user.get("stripe_customer_id")
                }}
            )
            logger.info(f"Device {device_id} is now Premium (from user)")
            return {"message": "Gerät erfolgreich verknüpft", "is_premium": True}
        
        elif device_is_premium and device.get("subscription_id"):
            # Device has premium (paid on this device) - sync to user
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    "is_premium": True,
                    "subscription_id": device.get("subscription_id"),
                    "stripe_customer_id": device.get("stripe_customer_id")
                }}
            )
            logger.info(f"User {user_id} is now Premium (synced from device payment)")
            return {"message": "Gerät erfolgreich verknüpft", "is_premium": True}
        
        else:
            # Neither has premium - just link without changing premium status
            logger.info(f"Device {device_id} linked - no premium subscription")
            return {"message": "Gerät erfolgreich verknüpft", "is_premium": False}
        
    except Exception as e:
        logger.error(f"Error linking device: {e}")
        raise HTTPException(status_code=500, detail="Verknüpfung fehlgeschlagen")

@api_router.get("/auth/user/{user_id}")
async def get_user(user_id: str):
    """Get user information including premium status"""
    from bson import ObjectId
    
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        
        return {
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "picture": user.get("picture", ""),
            "is_premium": user.get("is_premium", False),
            "subscription_id": user.get("subscription_id")
        }
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        raise HTTPException(status_code=500, detail="Fehler beim Laden des Benutzers")

@api_router.get("/auth/premium-status/{email}")
async def get_premium_status_by_email(email: str):
    """Get premium status by email - THE SINGLE SOURCE OF TRUTH"""
    try:
        user = await db.users.find_one({"email": email})
        if not user:
            return {"is_premium": False, "message": "User not found"}
        
        is_premium = user.get("is_premium", False)
        logger.info(f"Premium check for {email}: {is_premium}")
        
        return {
            "is_premium": is_premium,
            "subscription_id": user.get("subscription_id"),
            "email": email
        }
    except Exception as e:
        logger.error(f"Error checking premium: {e}")
        return {"is_premium": False, "error": str(e)}

# API Endpoints
@api_router.post("/device/init", response_model=DeviceStatus)
async def init_device(input: DeviceInit):
    """Initialize or get device status"""
    device = await get_or_create_device(input.device_id)
    
    cards_today = len(device["cards_drawn_today"])
    # Fix: Premium users should show unlimited (999), free users show remaining cards
    if device["is_premium"]:
        remaining = 999  # Unlimited for premium
    else:
        remaining = max(0, 3 - cards_today)
    
    return DeviceStatus(
        device_id=device["device_id"],
        cards_drawn_today=cards_today,
        remaining_free_cards=remaining,
        is_premium=device["is_premium"],
        last_reset_date=device["last_reset_date"]
    )

@api_router.get("/device/{device_id}/status", response_model=DeviceStatus)
async def get_device_status(device_id: str):
    """Get device status"""
    device = await get_or_create_device(device_id)
    
    cards_today = len(device["cards_drawn_today"])
    # Fix: Premium users should show unlimited (999), free users show remaining cards
    if device["is_premium"]:
        remaining = 999  # Unlimited for premium
    else:
        remaining = max(0, 3 - cards_today)
    
    return DeviceStatus(
        device_id=device["device_id"],
        cards_drawn_today=cards_today,
        remaining_free_cards=remaining,
        is_premium=device["is_premium"],
        last_reset_date=device["last_reset_date"]
    )

@api_router.post("/card/draw", response_model=CardResponse)
async def draw_card(input: CardDraw):
    """Draw a random tarot card"""
    device = await get_or_create_device(input.device_id)
    
    # Check if user can draw a card
    cards_today = len(device["cards_drawn_today"])
    if not device["is_premium"] and cards_today >= 3:
        raise HTTPException(status_code=403, detail="Daily limit reached. Upgrade to premium for unlimited cards.")
    
    # Select a random card
    card_data = random.choice(TAROT_CARDS_DE)
    
    # Check if we have the card image in database
    card_db = await db.tarot_cards.find_one(
        {"card_id": card_data["card_id"]},
        {"image_base64": 1, "card_id": 1}
    )
    
    if card_db and card_db.get("image_base64"):
        image_base64 = card_db["image_base64"]
    else:
        # Generate new image
        image_base64 = await generate_card_image(card_data["name_de"], card_data["keywords_de"])
        
        # Save to database for future use
        if image_base64:
            await db.tarot_cards.update_one(
                {"card_id": card_data["card_id"]},
                {
                    "$set": {
                        "card_id": card_data["card_id"],
                        "name_de": card_data["name_de"],
                        "arcana_type": card_data["arcana_type"],
                        "keywords_de": card_data["keywords_de"],
                        "image_base64": image_base64
                    }
                },
                upsert=True
            )
    
    # Update device's drawn cards
    await db.devices.update_one(
        {"device_id": input.device_id},
        {
            "$push": {
                "cards_drawn_today": {
                    "card_id": card_data["card_id"],
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        }
    )
    
    return CardResponse(
        card_id=card_data["card_id"],
        name_de=card_data["name_de"],
        arcana_type=card_data["arcana_type"],
        keywords_de=card_data["keywords_de"],
        image_base64=image_base64
    )

@api_router.post("/card/interpret", response_model=InterpretationResponse)
async def interpret_card(input: InterpretationRequest):
    """Get AI interpretation for a card"""
    # Find card data
    card_data = next((c for c in TAROT_CARDS_DE if c["card_id"] == input.card_id), None)
    if not card_data:
        raise HTTPException(status_code=404, detail="Card not found")
    
    # Check if we have a cached interpretation (only for non-personalized requests)
    if not input.user_question and not input.life_situation:
        reading = await db.readings.find_one(
            {
                "device_id": input.device_id,
                "card_id": input.card_id,
                "created_at": {"$gte": datetime.utcnow() - timedelta(hours=24)}
            },
            {"interpretation": 1}
        )
        
        if reading and reading.get("interpretation"):
            return InterpretationResponse(interpretation=reading["interpretation"])
    
    # Generate new interpretation (with optional personalization)
    interpretation = await generate_interpretation(
        card_data["name_de"], 
        card_data["keywords_de"],
        include_moon=True,
        user_question=input.user_question,
        life_situation=input.life_situation
    )
    
    # Save reading
    await db.readings.insert_one({
        "device_id": input.device_id,
        "card_id": input.card_id,
        "card_name": card_data["name_de"],
        "interpretation": interpretation,
        "user_question": input.user_question,
        "life_situation": input.life_situation,
        "created_at": datetime.utcnow()
    })
    
    return InterpretationResponse(interpretation=interpretation)

@api_router.post("/subscription/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(input: CheckoutRequest):
    """Create Stripe checkout session for premium subscription WITH Customer"""
    import stripe
    stripe.api_key = STRIPE_API_KEY
    
    device = await get_or_create_device(input.device_id)
    
    success_url = f"{input.origin_url}/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{input.origin_url}/"
    
    # Check if user has a Google account linked - use their email for Stripe Customer
    user_email = None
    if device.get("user_id"):
        from bson import ObjectId
        try:
            user = await db.users.find_one({"_id": ObjectId(device["user_id"])})
            if user:
                user_email = user.get("email")
        except:
            pass
    
    try:
        # Create Stripe checkout session with Customer creation
        checkout_params = {
            "payment_method_types": ["card"],
            "line_items": [{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": "Arcana Premium",
                        "description": "Unbegrenzte Kartenlegungen pro Tag",
                    },
                    "unit_amount": 499,  # 4.99 EUR in cents
                    "recurring": {
                        "interval": "month"
                    }
                },
                "quantity": 1,
            }],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {
                "device_id": input.device_id,
                "subscription_type": "premium_monthly"
            },
            # Note: In subscription mode, Stripe automatically creates a customer
        }
        
        # Pre-fill email if available
        if user_email:
            checkout_params["customer_email"] = user_email
        
        session = stripe.checkout.Session.create(**checkout_params)
        
        # Create payment transaction record
        await db.payment_transactions.insert_one({
            "session_id": session.id,
            "device_id": input.device_id,
            "amount": 4.99,
            "currency": "eur",
            "status": "pending",
            "payment_status": "initiated",
            "metadata": {"device_id": input.device_id, "subscription_type": "premium_monthly"},
            "created_at": datetime.utcnow()
        })
        
        return CheckoutSessionResponse(
            session_id=session.id,
            url=session.url
        )
        
    except Exception as e:
        logger.error(f"Error creating checkout: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    import stripe
    stripe.api_key = STRIPE_API_KEY
    
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    
    # Get webhook secret from env (you need to set this in Stripe Dashboard)
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    
    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(body, signature, webhook_secret)
        else:
            # Without webhook secret, parse the event directly (less secure)
            import json
            event = stripe.Event.construct_from(json.loads(body), stripe.api_key)
        
        logger.info(f"Webhook event type: {event.type}")
        
        # Handle checkout.session.completed event
        if event.type == "checkout.session.completed":
            session = event.data.object
            
            device_id = session.metadata.get("device_id")
            customer_id = session.customer
            subscription_id = session.subscription
            
            logger.info(f"Payment completed - device: {device_id}, customer: {customer_id}, subscription: {subscription_id}")
            
            # Update payment transaction
            await db.payment_transactions.update_one(
                {"session_id": session.id},
                {
                    "$set": {
                        "status": "completed",
                        "payment_status": "paid",
                        "customer_id": customer_id,
                        "subscription_id": subscription_id,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Update device to premium
            if device_id:
                await db.devices.update_one(
                    {"device_id": device_id},
                    {
                        "$set": {
                            "is_premium": True,
                            "subscription_id": subscription_id or session.id,
                            "stripe_customer_id": customer_id,
                            "upgraded_at": datetime.utcnow()
                        }
                    }
                )
                
                # Also update the user if linked
                device = await db.devices.find_one({"device_id": device_id})
                if device and device.get("user_id"):
                    from bson import ObjectId
                    await db.users.update_one(
                        {"_id": ObjectId(device["user_id"])},
                        {
                            "$set": {
                                "is_premium": True,
                                "subscription_id": subscription_id or session.id,
                                "stripe_customer_id": customer_id
                            }
                        }
                    )
        
        # Handle subscription cancelled/deleted
        elif event.type in ["customer.subscription.deleted", "customer.subscription.updated"]:
            subscription = event.data.object
            
            if event.type == "customer.subscription.deleted" or subscription.status == "canceled":
                customer_id = subscription.customer
                
                # Find devices with this customer and remove premium
                await db.devices.update_many(
                    {"stripe_customer_id": customer_id},
                    {"$set": {"is_premium": False}}
                )
                
                # Update users too
                await db.users.update_many(
                    {"stripe_customer_id": customer_id},
                    {"$set": {"is_premium": False}}
                )
                
                logger.info(f"Subscription cancelled for customer: {customer_id}")
        
        return {"received": True}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@api_router.get("/subscription/status/{device_id}", response_model=SubscriptionStatus)
async def get_subscription_status(device_id: str):
    """Get subscription status for device"""
    device = await get_or_create_device(device_id)
    
    return SubscriptionStatus(
        is_premium=device["is_premium"],
        subscription_id=device.get("subscription_id"),
        status="active" if device["is_premium"] else "inactive"
    )

class CustomerPortalRequest(BaseModel):
    device_id: str
    return_url: str

class CustomerPortalResponse(BaseModel):
    url: Optional[str] = None
    message: Optional[str] = None

@api_router.post("/subscription/portal", response_model=CustomerPortalResponse)
async def create_customer_portal(input: CustomerPortalRequest):
    """Create Stripe Customer Portal session for subscription management"""
    import stripe
    stripe.api_key = STRIPE_API_KEY
    
    logger.info(f"Portal request for device: {input.device_id}")
    
    device = await get_or_create_device(input.device_id)
    logger.info(f"Device is_premium: {device.get('is_premium')}")
    
    if not device.get("is_premium"):
        return CustomerPortalResponse(url=None, message="Kein aktives Abo gefunden. Bitte kaufe zuerst ein Premium-Abo.")
    
    # Find the payment transaction to get customer info
    subscription_id = device.get("subscription_id")
    
    try:
        # First, try to get the checkout session
        if subscription_id and subscription_id.startswith("cs_"):
            session = stripe.checkout.Session.retrieve(subscription_id)
            customer_id = session.customer
            
            if customer_id:
                logger.info(f"Found customer: {customer_id}")
                
                # Create Billing Portal session
                portal_session = stripe.billing_portal.Session.create(
                    customer=customer_id,
                    return_url=input.return_url
                )
                
                return CustomerPortalResponse(url=portal_session.url)
        
        # If no customer found, try to find by subscription ID
        if subscription_id and subscription_id.startswith("sub_"):
            subscription = stripe.Subscription.retrieve(subscription_id)
            customer_id = subscription.customer
            
            if customer_id:
                portal_session = stripe.billing_portal.Session.create(
                    customer=customer_id,
                    return_url=input.return_url
                )
                return CustomerPortalResponse(url=portal_session.url)
        
        # Fallback: Look for customer by stored customer_id
        stored_customer_id = device.get("stripe_customer_id")
        if stored_customer_id:
            portal_session = stripe.billing_portal.Session.create(
                customer=stored_customer_id,
                return_url=input.return_url
            )
            return CustomerPortalResponse(url=portal_session.url)
        
        return CustomerPortalResponse(
            url=None, 
            message="Kein Stripe-Kunde gefunden. Für ältere Abos bitte Support kontaktieren: ask@arcanaapp.me"
        )
        
    except stripe.error.InvalidRequestError as e:
        logger.error(f"Stripe error: {e}")
        if "portal" in str(e).lower() and "configuration" in str(e).lower():
            return CustomerPortalResponse(
                url=None, 
                message="Bitte aktiviere das Stripe Customer Portal im Dashboard: Settings → Billing → Customer Portal"
            )
        return CustomerPortalResponse(url=None, message=f"Stripe Fehler: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating portal: {e}")
        return CustomerPortalResponse(url=None, message="Fehler beim Erstellen des Portals")

@api_router.get("/checkout/status/{session_id}", response_model=CheckoutStatusResponse)
async def get_checkout_status(session_id: str, device_id: str = None):
    """Get checkout session status"""
    backend_url = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '')
    if not backend_url:
        raise HTTPException(status_code=500, detail="EXPO_PUBLIC_BACKEND_URL not configured")
    
    webhook_url = f"{backend_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    try:
        status = await stripe_checkout.get_checkout_status(session_id)
        
        # Update transaction if payment completed
        if status.payment_status == "paid":
            # First try to find transaction by session_id
            transaction = await db.payment_transactions.find_one(
                {"session_id": session_id},
                {"payment_status": 1, "device_id": 1}
            )
            
            # Get device_id from transaction or from query param
            target_device_id = None
            if transaction:
                target_device_id = transaction.get("device_id")
            elif device_id:
                target_device_id = device_id
            
            logger.info(f"Checkout status check - session: {session_id}, device: {target_device_id}, paid: True")
            
            # Update transaction record
            if transaction and transaction.get("payment_status") != "paid":
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {
                        "$set": {
                            "status": "completed",
                            "payment_status": "paid",
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
            elif not transaction and device_id:
                # Create transaction record if it doesn't exist
                await db.payment_transactions.insert_one({
                    "session_id": session_id,
                    "device_id": device_id,
                    "amount": 4.99,
                    "currency": "eur",
                    "status": "completed",
                    "payment_status": "paid",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
            
            # Update device to premium
            if target_device_id:
                result = await db.devices.update_one(
                    {"device_id": target_device_id},
                    {
                        "$set": {
                            "is_premium": True,
                            "subscription_id": session_id,
                            "upgraded_at": datetime.utcnow()
                        }
                    }
                )
                logger.info(f"Device premium update result: matched={result.matched_count}, modified={result.modified_count}")
        
        return status
    except Exception as e:
        logger.error(f"Error checking checkout status: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# Manual activation endpoint for admin use
class ManualActivationRequest(BaseModel):
    device_id: str
    admin_key: str

@api_router.post("/admin/activate-premium")
async def manual_activate_premium(input: ManualActivationRequest):
    """Manually activate premium for a device (admin only)"""
    # Simple admin key check (you should change this!)
    if input.admin_key != "arcana-admin-2024":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    result = await db.devices.update_one(
        {"device_id": input.device_id},
        {
            "$set": {
                "is_premium": True,
                "subscription_id": "manual_activation",
                "upgraded_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    
    logger.info(f"Manual premium activation for device: {input.device_id}")
    return {"message": "Premium activated", "device_id": input.device_id}

class SyncPremiumRequest(BaseModel):
    user_id: str
    admin_key: str

@api_router.post("/admin/sync-premium-to-user")
async def sync_premium_to_user(input: SyncPremiumRequest):
    """Sync premium status to a user and all their devices (admin only)"""
    from bson import ObjectId
    
    if input.admin_key != "arcana-admin-2024":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    try:
        # Update user to premium
        await db.users.update_one(
            {"_id": ObjectId(input.user_id)},
            {
                "$set": {
                    "is_premium": True,
                    "subscription_id": "manual_sync",
                    "upgraded_at": datetime.utcnow()
                }
            }
        )
        
        # Update all devices linked to this user
        result = await db.devices.update_many(
            {"user_id": input.user_id},
            {
                "$set": {
                    "is_premium": True,
                    "subscription_id": "manual_sync",
                    "upgraded_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Synced premium to user {input.user_id}, updated {result.modified_count} devices")
        return {
            "message": "Premium synced", 
            "user_id": input.user_id,
            "devices_updated": result.modified_count
        }
    except Exception as e:
        logger.error(f"Error syncing premium: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/iap/verify", response_model=IAPVerifyResponse)
async def verify_iap_receipt(input: IAPVerifyRequest):
    """Verify Apple IAP receipt and activate premium"""
    try:
        logger.info(f"IAP: Verifying receipt for device {input.device_id}")
        
        # In production, you would verify the receipt with Apple's servers
        # For now, we'll do a simple validation
        if not input.receipt or len(input.receipt) < 10:
            raise HTTPException(status_code=400, detail="Invalid receipt")
        
        # Check if receipt was already processed
        existing = await db.iap_transactions.find_one({
            "transaction_id": input.transaction_id
        })
        
        if existing:
            logger.info(f"IAP: Receipt already processed for transaction {input.transaction_id}")
            # Check if device is premium
            device = await get_or_create_device(input.device_id)
            return IAPVerifyResponse(
                success=True,
                is_premium=device["is_premium"],
                message="Receipt already processed"
            )
        
        # Save IAP transaction
        await db.iap_transactions.insert_one({
            "device_id": input.device_id,
            "receipt": input.receipt,
            "product_id": input.product_id,
            "transaction_id": input.transaction_id,
            "platform": "ios",
            "status": "verified",
            "created_at": datetime.utcnow()
        })
        
        # Update device to premium
        await db.devices.update_one(
            {"device_id": input.device_id},
            {
                "$set": {
                    "is_premium": True,
                    "subscription_id": input.transaction_id,
                    "subscription_type": "apple_iap",
                    "upgraded_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"IAP: Device {input.device_id} upgraded to premium via Apple IAP")
        
        return IAPVerifyResponse(
            success=True,
            is_premium=True,
            message="Premium activated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying IAP receipt: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify receipt")

# NEW ENDPOINTS FOR JOURNAL & HISTORY FEATURES

@api_router.post("/card/draw-spread", response_model=MultiCardResponse)
async def draw_spread(input: MultiCardDrawRequest):
    """Draw multiple cards for a spread (3-card: Past-Present-Future)"""
    device = await get_or_create_device(input.device_id)
    
    # Determine number of cards based on spread type
    spread_configs = {
        "single": {"count": 1, "positions": ["Deine Karte"]},
        "three_card": {"count": 3, "positions": ["Vergangenheit", "Gegenwart", "Zukunft"]},
        "past_present_future": {"count": 3, "positions": ["Vergangenheit", "Gegenwart", "Zukunft"]},
    }
    
    config = spread_configs.get(input.spread_type, spread_configs["single"])
    num_cards = config["count"]
    positions = config["positions"]
    
    # Check if user can draw cards
    cards_today = len(device["cards_drawn_today"])
    if not device["is_premium"] and cards_today + num_cards > 3:
        raise HTTPException(status_code=403, detail="Daily limit reached. Upgrade to premium for unlimited cards.")
    
    # Select random cards (no duplicates)
    selected_cards = random.sample(TAROT_CARDS_DE, num_cards)
    
    # Create a reading session ID
    reading_id = str(uuid.uuid4())
    
    # First, get all cached images in parallel
    async def get_card_with_image(card_data, position_index):
        card_db = await db.tarot_cards.find_one(
            {"card_id": card_data["card_id"]},
            {"image_base64": 1}
        )
        
        if card_db and card_db.get("image_base64"):
            image_base64 = card_db["image_base64"]
        else:
            # Generate image (this is the slow part)
            image_base64 = await generate_card_image(card_data["name_de"], card_data["keywords_de"])
            if image_base64:
                await db.tarot_cards.update_one(
                    {"card_id": card_data["card_id"]},
                    {"$set": {
                        "card_id": card_data["card_id"],
                        "name_de": card_data["name_de"],
                        "image_base64": image_base64
                    }},
                    upsert=True
                )
        
        return CardResponse(
            card_id=card_data["card_id"],
            name_de=card_data["name_de"],
            arcana_type=card_data["arcana_type"],
            keywords_de=card_data["keywords_de"],
            image_base64=image_base64
        ), position_index
    
    # Run all card fetches in parallel
    import asyncio
    tasks = [get_card_with_image(card, i) for i, card in enumerate(selected_cards)]
    results = await asyncio.gather(*tasks)
    
    # Sort by position index and extract cards
    results.sort(key=lambda x: x[1])
    cards_response = [r[0] for r in results]
    
    # Update device's drawn cards (all at once)
    card_updates = []
    for i, card_data in enumerate(selected_cards):
        card_updates.append({
            "card_id": card_data["card_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "reading_id": reading_id,
            "position": positions[i]
        })
    
    await db.devices.update_one(
        {"device_id": input.device_id},
        {"$push": {"cards_drawn_today": {"$each": card_updates}}}
    )
    
    # Save the reading session
    await db.readings.insert_one({
        "reading_id": reading_id,
        "device_id": input.device_id,
        "spread_type": input.spread_type,
        "cards": [{"card_id": c.card_id, "card_name": c.name_de, "position": positions[i]} for i, c in enumerate(cards_response)],
        "note": None,
        "created_at": datetime.utcnow()
    })
    
    return MultiCardResponse(
        spread_type=input.spread_type,
        cards=cards_response,
        positions=positions
    )

@api_router.get("/readings/history/{device_id}", response_model=HistoryResponse)
async def get_reading_history(device_id: str, limit: int = 50, skip: int = 0):
    """Get reading history for a device"""
    readings = await db.readings.find(
        {"device_id": device_id}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    
    total_count = await db.readings.count_documents({"device_id": device_id})
    
    history = []
    for reading in readings:
        # Handle both old single-card readings and new multi-card readings
        if "cards" in reading:
            # Multi-card reading
            for card_info in reading["cards"]:
                history.append(ReadingHistory(
                    reading_id=reading.get("reading_id", str(reading["_id"])),
                    card_id=card_info["card_id"],
                    card_name=card_info["card_name"],
                    interpretation=reading.get("interpretation", ""),
                    note=reading.get("note"),
                    created_at=reading["created_at"].isoformat() if isinstance(reading["created_at"], datetime) else reading["created_at"],
                    spread_type=reading.get("spread_type", "single"),
                    spread_position=card_info.get("position")
                ))
        else:
            # Old single-card reading
            history.append(ReadingHistory(
                reading_id=str(reading["_id"]),
                card_id=reading["card_id"],
                card_name=reading["card_name"],
                interpretation=reading.get("interpretation", ""),
                note=reading.get("note"),
                created_at=reading["created_at"].isoformat() if isinstance(reading["created_at"], datetime) else reading["created_at"],
                spread_type="single",
                spread_position=None
            ))
    
    return HistoryResponse(readings=history, total_count=total_count)

@api_router.post("/readings/note")
async def save_reading_note(input: ReadingNote):
    """Save a note for a reading"""
    result = await db.readings.update_one(
        {"reading_id": input.reading_id, "device_id": input.device_id},
        {"$set": {"note": input.note, "note_updated_at": datetime.utcnow()}}
    )
    
    if result.modified_count == 0:
        # Try with _id if reading_id doesn't work
        from bson import ObjectId
        try:
            await db.readings.update_one(
                {"_id": ObjectId(input.reading_id), "device_id": input.device_id},
                {"$set": {"note": input.note, "note_updated_at": datetime.utcnow()}}
            )
        except:
            raise HTTPException(status_code=404, detail="Reading not found")
    
    return {"success": True, "message": "Note saved"}

@api_router.get("/readings/{reading_id}")
async def get_reading(reading_id: str, device_id: str):
    """Get a specific reading with its note"""
    reading = await db.readings.find_one({
        "reading_id": reading_id,
        "device_id": device_id
    })
    
    if not reading:
        from bson import ObjectId
        try:
            reading = await db.readings.find_one({
                "_id": ObjectId(reading_id),
                "device_id": device_id
            })
        except:
            raise HTTPException(status_code=404, detail="Reading not found")
    
    if not reading:
        raise HTTPException(status_code=404, detail="Reading not found")
    
    return {
        "reading_id": reading.get("reading_id", str(reading["_id"])),
        "card_id": reading.get("card_id"),
        "card_name": reading.get("card_name"),
        "cards": reading.get("cards", []),
        "interpretation": reading.get("interpretation", ""),
        "note": reading.get("note"),
        "spread_type": reading.get("spread_type", "single"),
        "created_at": reading["created_at"].isoformat() if isinstance(reading["created_at"], datetime) else reading["created_at"]
    }

# MOON PHASE ENDPOINT
@api_router.get("/moon-phase")
async def get_current_moon_phase():
    """Get current moon phase information"""
    moon_info = get_moon_phase_info()
    return moon_info

# SCREENSHOT MODE - Remove limits temporarily
@api_router.post("/screenshot-mode/{device_id}")
async def enable_screenshot_mode(device_id: str):
    """Enable unlimited cards for screenshots"""
    await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"is_premium": True, "remaining_free_cards": 999}}
    )
    return {"status": "Screenshot mode enabled", "is_premium": True}

# CARD STATISTICS ENDPOINT
class CardStatistic(BaseModel):
    card_id: int
    card_name: str
    count: int
    percentage: float
    arcana_type: str

class StatisticsResponse(BaseModel):
    total_readings: int
    most_drawn_cards: List[CardStatistic]
    arcana_distribution: Dict[str, int]
    favorite_card: Optional[CardStatistic] = None
    reading_streak: int  # Days with consecutive readings
    last_reading_date: Optional[str] = None

@api_router.get("/statistics/{device_id}", response_model=StatisticsResponse)
async def get_card_statistics(device_id: str):
    """Get personal card statistics for a device"""
    # Get all readings for this device
    readings = await db.readings.find({"device_id": device_id}).to_list(length=1000)
    
    if not readings:
        return StatisticsResponse(
            total_readings=0,
            most_drawn_cards=[],
            arcana_distribution={"major": 0, "minor": 0},
            favorite_card=None,
            reading_streak=0,
            last_reading_date=None
        )
    
    # Count card occurrences
    card_counts = {}
    arcana_counts = {"major": 0, "minor": 0}
    reading_dates = set()
    
    for reading in readings:
        # Handle multi-card readings
        if "cards" in reading:
            for card_info in reading["cards"]:
                card_id = card_info["card_id"]
                card_name = card_info["card_name"]
                card_counts[card_id] = card_counts.get(card_id, {"name": card_name, "count": 0})
                card_counts[card_id]["count"] += 1
                
                # Get arcana type
                card_data = next((c for c in TAROT_CARDS_DE if c["card_id"] == card_id), None)
                if card_data:
                    arcana_counts[card_data["arcana_type"]] += 1
        else:
            # Single card reading
            card_id = reading.get("card_id")
            card_name = reading.get("card_name")
            if card_id is not None:
                card_counts[card_id] = card_counts.get(card_id, {"name": card_name, "count": 0})
                card_counts[card_id]["count"] += 1
                
                card_data = next((c for c in TAROT_CARDS_DE if c["card_id"] == card_id), None)
                if card_data:
                    arcana_counts[card_data["arcana_type"]] += 1
        
        # Track reading dates for streak calculation
        created_at = reading.get("created_at")
        if isinstance(created_at, datetime):
            reading_dates.add(created_at.date())
        elif isinstance(created_at, str):
            try:
                reading_dates.add(datetime.fromisoformat(created_at.replace("Z", "")).date())
            except:
                pass
    
    # Calculate total
    total = sum(c["count"] for c in card_counts.values())
    
    # Sort by count and get top cards
    sorted_cards = sorted(card_counts.items(), key=lambda x: x[1]["count"], reverse=True)
    
    most_drawn = []
    for card_id, info in sorted_cards[:5]:
        card_data = next((c for c in TAROT_CARDS_DE if c["card_id"] == card_id), None)
        arcana_type = card_data["arcana_type"] if card_data else "unknown"
        most_drawn.append(CardStatistic(
            card_id=card_id,
            card_name=info["name"],
            count=info["count"],
            percentage=round((info["count"] / total) * 100, 1) if total > 0 else 0,
            arcana_type=arcana_type
        ))
    
    # Calculate reading streak
    streak = 0
    if reading_dates:
        sorted_dates = sorted(reading_dates, reverse=True)
        today = datetime.utcnow().date()
        current_date = today
        
        for date in sorted_dates:
            if date == current_date or date == current_date - timedelta(days=1):
                streak += 1
                current_date = date
            else:
                break
    
    # Get last reading date
    last_reading = None
    if readings:
        latest = max(readings, key=lambda r: r.get("created_at", datetime.min) if isinstance(r.get("created_at"), datetime) else datetime.min)
        created_at = latest.get("created_at")
        if isinstance(created_at, datetime):
            last_reading = created_at.isoformat()
        elif isinstance(created_at, str):
            last_reading = created_at
    
    return StatisticsResponse(
        total_readings=len(readings),
        most_drawn_cards=most_drawn,
        arcana_distribution=arcana_counts,
        favorite_card=most_drawn[0] if most_drawn else None,
        reading_streak=streak,
        last_reading_date=last_reading
    )

# Health check endpoint
@api_router.get("/health")
async def health_check():
    """Health check endpoint for deployment monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "arcana-tarot-backend",
        "version": "1.0.0"
    }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
