import os
from dotenv import load_dotenv
import google.generativeai as genai
from app.database import SessionLocal
from app.models import Voucher, InventoryItem, SupplierProfile
from app.explainability import get_shap_sales_drivers

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY", "")
if api_key:
    genai.configure(api_key=api_key)

class ArthPulseAIService:
    def __init__(self):
        # Using Gemini Flash for fast and accurate conversational responses
        self.model_name = "gemini-2.5-flash"
    
    def _get_live_context(self, period="monthly"):
        """Gathers aggregated financial metrics from summaries.build_summary to ground the LLM."""
        try:
            from app.summaries import build_summary
            db = SessionLocal()
            summary = build_summary(db, period=period)
            summary["root_cause_shap_analysis"] = get_shap_sales_drivers(db, period=period)
            db.close()
            return summary
        except Exception as e:
            # Fallback direct summary if any issue occurs
            try:
                db = SessionLocal()
                total_sales = sum(v.amount for v in db.query(Voucher).filter(Voucher.voucher_type == "Sales").all())
                total_purchases = sum(v.amount for v in db.query(Voucher).filter(Voucher.voucher_type == "Purchase").all())
                total_stock = sum(i.value for i in db.query(InventoryItem).all())
                db.close()
                return {
                    "overview": {
                        "net_sales": total_sales,
                        "sales_less_purchases": total_sales - total_purchases,
                        "stock_value": total_stock
                    },
                    "period": period
                }
            except Exception as inner_e:
                return {"error": str(inner_e)}

    def answer_query(self, user_prompt: str, period: str = "monthly"):
        context_data = self._get_live_context(period)
        
        system_instruction = f"""
        You are the ArthPulse AI Assistant, an expert business intelligence co-pilot for Small and Medium Enterprises using TallyPrime.
        
        CRITICAL RULES:
        1. Answer the user's question in clear, professional, plain English.
        2. Ground your answer STRICTLY in the provided dashboard data context below.
        3. **NEVER** mention "SHAP", "machine learning", "attributions", or "impact scores". Translate any underlying model insights into natural business language (e.g., explain what drove a trend without exposing technical terms or raw scores).
        4. **FORMATTING:** Never use asterisks (*) inline. Whenever you list items, you MUST insert actual line breaks (press enter / use \\n) before every single dash so they appear as separate vertical bullet rows. For example:
           
           Here are the primary factors:
           - First point here
           - Second point here
        
        CURRENT APPROVED DASHBOARD DATA & CONTEXT ({period}):
        {context_data}
        """
        prompt = f"""
        {system_instruction}
        
        User Question: {user_prompt}
        """

        try:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=2000
                )
            )
            
            return {
                "status": "success",
                "answer": response.text,
                "period": period,
                "grounded_in_data": True
            }
        except Exception as e:
            return {
                "status": "error",
                "answer": f"I encountered an issue generating the AI response: {str(e)}. Please ensure your GEMINI_API_KEY is configured in your .env file.",
                "grounded_in_data": False
            }

    def _get_live_context(self, period="monthly"):
        try:
            from app.summaries import build_summary
            from app.database import SessionLocal
            
            db = SessionLocal()
            summary = build_summary(db, period=period)
            
            # Inject SHAP root-cause metrics into the context payload
            shap_insights = get_shap_sales_drivers(db, period=period)
            summary["root_cause_shap_analysis"] = shap_insights
            
            db.close()
            return summary
        except Exception as e:
            return {"error": str(e)}
        
ai_service = ArthPulseAIService()