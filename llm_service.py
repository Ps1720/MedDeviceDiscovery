"""
LLM Service for Medical Device Discovery

This module integrates with OpenAI GPT to provide an AI assistant that can
answer questions about medical devices. It uses device information from
both the local database and FDA GUDID to provide context-aware responses.

Supports custom API base URLs for Azure OpenAI or other compatible endpoints.
"""

from openai import OpenAI
from config import Config

# Initialize OpenAI client (lazy loading)
_client = None


def get_client():
    """Get or create the OpenAI client."""
    global _client
    if _client is None and Config.OPENAI_API_KEY:
        _client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_API_BASE
        )
    return _client


# System prompt for the medical device assistant
SYSTEM_PROMPT = """You are a medical device assistant helping anesthesia providers quickly understand and operate medical equipment they encounter in clinical settings.

You have access to device information provided below. Your job is to:
- Give clear, concise answers
- Provide step-by-step instructions when needed
- Highlight safety warnings when relevant (especially MRI safety!)
- Describe button locations and interface elements clearly
- Keep responses brief and scannable (users are in busy clinical environments)

If you don't have specific information, use your general knowledge of similar devices and clearly indicate when you're providing general guidance vs. device-specific information.

If asked about something you truly don't know, suggest the user:
1. Check the physical device label
2. Contact the manufacturer
3. Consult hospital biomedical engineering

DEVICE INFORMATION:
{device_context}

Remember: Be helpful, be safe, be brief."""


def build_device_context(device: dict) -> str:
    """
    Build context string from device data.
    
    Works with both local database devices and GUDID devices.
    
    Args:
        device: Device information dictionary
        
    Returns:
        Formatted context string for the LLM
    """
    if not device:
        return "No device information available."
    
    # Basic info
    context = f"""
Manufacturer: {device.get('manufacturer', device.get('companyName', 'Unknown'))}
Brand/Model: {device.get('brand_name', '')} {device.get('model', device.get('versionModelNumber', 'Unknown'))}
Type: {device.get('type', 'Medical Device')}
Description: {device.get('description', device.get('deviceDescription', 'N/A'))}

Data Source: {device.get('source', 'Unknown').upper()}
"""

    # Add GUDID-specific safety info
    if device.get('source') == 'gudid':
        context += f"""
=== FDA GUDID SAFETY DATA ===
MRI Safety Status: {device.get('mri_safety', 'Not specified')}
Single Use: {'Yes' if device.get('single_use') else 'No' if device.get('single_use') is False else 'Not specified'}
Sterile: {'Yes' if device.get('sterile') else 'No' if device.get('sterile') is False else 'Not specified'}
Contains Latex: {'Yes' if device.get('contains_latex') else 'No' if device.get('contains_latex') is False else 'Not specified'}
Device Class: {device.get('device_class', 'Not specified')}
"""
        if device.get('gmdn_definition'):
            context += f"GMDN Definition: {device.get('gmdn_definition')}\n"

    # Add local database info (quick tips, alarms, etc.)
    if device.get('features'):
        context += f"\nFeatures: {', '.join(device.get('features', []))}\n"
    
    if device.get('quick_tips'):
        context += "\nQuick Tips:\n"
        for tip in device.get('quick_tips', []):
            context += f"• {tip}\n"
    
    if device.get('common_alarms'):
        context += "\nCommon Alarms:\n"
        for alarm in device.get('common_alarms', []):
            context += f"• {alarm.get('code', 'N/A')}: {alarm.get('meaning', '')} → {alarm.get('action', '')}\n"
    
    return context


def ask_device_question(device: dict, question: str, chat_history: list = None) -> str:
    """
    Ask a question about a device using OpenAI GPT.
    
    Args:
        device: Device information dictionary (local or GUDID)
        question: User's question
        chat_history: Optional list of previous messages for context
    
    Returns:
        AI response string
    """
    api_client = get_client()
    
    if not api_client:
        return ("AI assistant is not configured. Please set OPENAI_API_KEY in your environment. "
                "You can still view the device information above.")
    
    # Build context from device info
    device_context = build_device_context(device)
    
    # Build messages array with system prompt
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(device_context=device_context)
        }
    ]
    
    # Add chat history for context
    if chat_history:
        for msg in chat_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
    
    # Add current question
    messages.append({
        "role": "user",
        "content": question
    })
    
    try:
        response = api_client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0.7
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


def get_quick_questions(device_type: str) -> list:
    """
    Get suggested quick questions based on device type.
    
    Args:
        device_type: The type/category of the device
        
    Returns:
        List of suggested questions
    """
    # Normalize device type for matching
    device_type_lower = (device_type or "").lower()
    
    # Patient monitors
    if "monitor" in device_type_lower:
        return [
            "How do I silence the alarms?",
            "How do I change alarm limits?",
            "How do I print a waveform strip?",
            "What do the different alarm sounds mean?",
            "How do I start a NIBP measurement?"
        ]
    
    # Anesthesia machines
    elif "anesthesia" in device_type_lower or "anaesthesia" in device_type_lower:
        return [
            "How do I do a pre-use checkout?",
            "How do I change ventilation mode?",
            "How do I adjust fresh gas flow?",
            "How do I refill the vaporizer?",
            "What does this alarm mean?"
        ]
    
    # Infusion pumps
    elif "pump" in device_type_lower or "infusion" in device_type_lower:
        return [
            "How do I program a new infusion?",
            "How do I clear an occlusion alarm?",
            "How do I set up a secondary infusion?",
            "How do I give a bolus?",
            "How do I change the rate?"
        ]
    
    # Ventilators
    elif "ventilator" in device_type_lower:
        return [
            "How do I change ventilation mode?",
            "How do I adjust FiO2?",
            "How do I set PEEP?",
            "What does this alarm mean?",
            "How do I do a recruitment maneuver?"
        ]
    
    # Stents, catheters, implantables (from GUDID)
    elif any(x in device_type_lower for x in ["stent", "catheter", "implant"]):
        return [
            "What are the specifications?",
            "What is the MRI safety status?",
            "Is this device single-use?",
            "What are the storage requirements?",
            "Who is the manufacturer contact?"
        ]
    
    # Defibrillators
    elif "defibrillator" in device_type_lower:
        return [
            "How do I use this in an emergency?",
            "How do I check the battery level?",
            "What do the different modes mean?",
            "How do I change the energy level?",
            "How do I switch between AED and manual mode?"
        ]
    
    # Default questions
    else:
        return [
            "How do I use this device?",
            "What are the safety considerations?",
            "Is this MRI safe?",
            "What do the alarms mean?",
            "Where can I find the manual?"
        ]
