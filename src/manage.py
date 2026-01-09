#!/usr/bin/env python
"""
投资机会雷达 - 命令行管理工具
"""
import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.config import get_settings
from src.app.domain.models import Base, AppUser, Settings, PromptVersion
from src.app.core.security import hash_password


@click.group()
def cli():
    """投资机会雷达管理工具"""
    pass


@cli.command()
def init_db():
    """初始化数据库（创建所有表）"""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    
    click.echo("创建数据库表...")
    Base.metadata.create_all(engine)
    click.echo("✅ 数据库表创建完成")


@cli.command()
@click.option("--username", default=None, help="管理员用户名（默认从环境变量读取）")
@click.option("--password", default=None, help="管理员密码（默认从环境变量读取）")
def create_admin(username: str, password: str):
    """创建管理员账户"""
    settings = get_settings()
    
    # 如果没有指定，从环境变量读取
    username = username or settings.radar_admin_username
    password = password or settings.radar_admin_password
    
    if not username or not password:
        click.echo("❌ 请设置 RADAR_ADMIN_USERNAME 和 RADAR_ADMIN_PASSWORD 环境变量")
        return
    
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # 检查是否已存在
        existing = session.query(AppUser).filter(AppUser.username == username).first()
        if existing:
            click.echo(f"⚠️ 用户 {username} 已存在")
            return
        
        # 创建管理员
        admin = AppUser(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add(admin)
        session.commit()
        
        click.echo(f"✅ 管理员 {username} 创建成功")
    finally:
        session.close()


@cli.command()
def init_settings():
    """初始化默认配置"""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    default_settings = [
        ("push_score_threshold", 60),
        ("remember_me_days", 30),
        ("schedule_slots", ["07:00", "12:00", "14:00", "18:00", "22:00"]),
        ("window_days", 3),
    ]
    
    try:
        for key, value in default_settings:
            existing = session.query(Settings).filter(Settings.key == key).first()
            if not existing:
                setting = Settings(key=key, value_json=value)
                session.add(setting)
                click.echo(f"  + {key} = {value}")
            else:
                click.echo(f"  - {key} 已存在，跳过")
        
        session.commit()
        click.echo("✅ 默认配置初始化完成")
    finally:
        session.close()


@cli.command()
def init_prompts():
    """初始化默认 Prompt 模板"""
    from src.app.core.prompts import (
        OPPORTUNITY_ANALYZER_SYSTEM_PROMPT, 
        OPPORTUNITY_ANALYZER_USER_TEMPLATE,
        DAILY_DIGEST_SYSTEM_PROMPT,
        DAILY_DIGEST_USER_TEMPLATE
    )
    
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    prompts = [
        (
            "opportunity_analyzer", 
            OPPORTUNITY_ANALYZER_SYSTEM_PROMPT, 
            OPPORTUNITY_ANALYZER_USER_TEMPLATE, 
            60
        ),
        (
            "daily_digest", 
            DAILY_DIGEST_SYSTEM_PROMPT, 
            DAILY_DIGEST_USER_TEMPLATE, 
            None
        ),
    ]
    
    try:
        for name, system_prompt, user_template, threshold in prompts:
            existing = session.query(PromptVersion).filter(
                PromptVersion.name == name,
                PromptVersion.is_active == True,
            ).first()
            
            if not existing:
                prompt = PromptVersion(
                    name=name,
                    version=1,
                    is_active=True,
                    threshold=threshold,
                    system_prompt=system_prompt,
                    user_template=user_template,
                )
                session.add(prompt)
                click.echo(f"  + {name} v1 已创建并激活")
            else:
                click.echo(f"  - {name} 已有活跃版本 v{existing.version}，跳过")
        
        session.commit()
        click.echo("✅ Prompt 模板初始化完成")
    finally:
        session.close()


@cli.command()
def fix_prompts_schema():
    """修复 PromptVersion 表结构（增加 system_prompt/user_template）"""
    from sqlalchemy import text
    
    settings = get_settings()
    engine = create_engine(settings.database_url)
    
    click.echo("正在修复 PromptVersion 表结构...")
    
    with engine.connect() as conn:
        try:
            # 1. 添加新列
            click.echo("Adding columns system_prompt and user_template...")
            conn.execute(text("ALTER TABLE prompt_version ADD COLUMN IF NOT EXISTS system_prompt TEXT DEFAULT ''"))
            conn.execute(text("ALTER TABLE prompt_version ADD COLUMN IF NOT EXISTS user_template TEXT DEFAULT ''"))
            conn.commit()
            click.echo("✅ Columns added.")
        except Exception as e:
            click.echo(f"⚠️ Column add warning: {e}")

        try:
            # 2. 删除旧列 (SQLite 可能不支持 DROP COLUMN)
            click.echo("Dropping column prompt_text...")
            conn.execute(text("ALTER TABLE prompt_version DROP COLUMN IF EXISTS prompt_text"))
            conn.commit()
            click.echo("✅ Column dropped.")
        except Exception as e:
            click.echo(f"⚠️ Drop column warning: {e}")
            
    click.echo("🎉 结构修复完成")


@cli.command()
def init_all():
    """一键初始化：数据库 + 管理员 + 默认配置 + Prompt"""
    from click.testing import CliRunner
    runner = CliRunner()
    
    click.echo("=" * 50)
    click.echo("初始化数据库...")
    result = runner.invoke(init_db)
    click.echo(result.output)
    
    click.echo("=" * 50)
    click.echo("创建管理员...")
    result = runner.invoke(create_admin)
    click.echo(result.output)
    
    click.echo("=" * 50)
    click.echo("初始化默认配置...")
    result = runner.invoke(init_settings)
    click.echo(result.output)
    
    click.echo("=" * 50)
    click.echo("初始化 Prompt 模板...")
    result = runner.invoke(init_prompts)
    click.echo(result.output)
    
    click.echo("=" * 50)
    click.echo("🎉 初始化完成！")


@cli.command()
@click.argument("slot")
def run_slot_manual(slot: str):
    """手动触发一个 slot 任务（用于测试）"""
    from src.app.tasks.slot import run_slot
    click.echo(f"手动触发 slot: {slot}")
    result = run_slot(slot)
    click.echo(f"结果: {result}")


if __name__ == "__main__":
    cli()
