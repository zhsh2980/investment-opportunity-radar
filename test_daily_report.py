from datetime import date
from src.app.database import SessionLocal
from src.app.tasks.slot import generate_and_push_daily_report
from src.app.domain.models import ContentItem, AnalysisResult
from unittest.mock import patch, MagicMock

def test_daily_report_fallback():
    session = SessionLocal()
    try:
        # Mock DeepSeek to raise an exception
        with patch('src.app.clients.deepseek.DeepSeekClient.analyze_article') as mock_analyze:
            mock_analyze.side_effect = Exception("Simulated DeepSeek Failure")
            
            # Use yesterday's date or today depending on data, but let's just run it
            # This will fetch real data from DB but fail at AI generation step
            # We want to see if it catches the exception and returns True (success in pushing fallback report)
            
            # Mock DingTalk so we don't actually spam notifications, but print what would be sent
            with patch('src.app.clients.dingtalk.DingTalkClient.send_daily_report') as mock_send:
                mock_send.return_value = {"errcode": 0}
                
                print("Running generate_and_push_daily_report with simulated AI failure...")
                today = date.today()
                success = generate_and_push_daily_report(
                    session=session,
                    run_date=today,
                    slot="TEST",
                    base_url="http://localhost"
                )
                
                if success:
                    print("✅ generate_and_push_daily_report returned True (Success)")
                    # Verify what was sent
                    args = mock_send.call_args[1]
                    digest = args.get('digest', '')
                    print(f"Digest Content Preview:\n---\n{digest}\n---")
                    
                    if "AI 生成遇到问题" in digest:
                        print("✅ Fallback message detected in digest.")
                    else:
                        print("❌ Fallback message NOT detected.")
                else:
                    print("❌ generate_and_push_daily_report returned False (Failed)")

    except Exception as e:
        print(f"❌ Test script crashed: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    test_daily_report_fallback()
