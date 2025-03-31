from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
import os
import json
import time
import shutil
import logging
import re
import zipfile
from datetime import datetime
from django.contrib.admin.models import LogEntry
from django.core import management
from django.http import HttpResponse
from django.utils.text import slugify

from .permissions.decorators import permission_required
from .utils.logging import log_view_access
from .services.backup_service import BackupService

# 获取logger
logger = logging.getLogger(__name__)

def get_dir_size_display(dir_path):
    """获取目录大小的友好显示"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(dir_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    
    # 转换为合适的单位
    size_bytes = total_size
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

@login_required
@log_view_access('OTHER')
@permission_required('is_superuser')
def system_settings(request):
    """
    系统设置视图
    """
    context = {
        'settings': {
            'debug_mode': settings.DEBUG,
            'media_root': settings.MEDIA_ROOT,
            'timezone': settings.TIME_ZONE,
            'database_engine': settings.DATABASES['default']['ENGINE'],
            'version': getattr(settings, 'VERSION', '1.0.0'),
        }
    }
    return render(request, 'inventory/system/settings.html', context)

@login_required
@permission_required('inventory.can_manage_backup')
def backup_list(request):
    """备份列表视图"""
    # 检查备份目录是否存在
    if not os.path.exists(settings.BACKUP_ROOT):
        os.makedirs(settings.BACKUP_ROOT, exist_ok=True)
    
    # 获取所有备份
    backups = []
    for backup_name in os.listdir(settings.BACKUP_ROOT):
        backup_dir = os.path.join(settings.BACKUP_ROOT, backup_name)
        if os.path.isdir(backup_dir):
            # 读取备份信息
            backup_info_file = os.path.join(backup_dir, 'backup_info.json')
            try:
                if os.path.exists(backup_info_file):
                    with open(backup_info_file, 'r', encoding='utf-8') as f:
                        backup_info = json.load(f)
                    
                    backups.append({
                        'name': backup_name,
                        'created_at': datetime.fromisoformat(backup_info.get('created_at', '')),
                        'created_by': backup_info.get('created_by', '未知'),
                        'size': get_dir_size_display(backup_dir),
                    })
            except Exception as e:
                logger.error(f"读取备份信息失败: {str(e)}")
    
    # 按创建时间排序
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    
    return render(request, 'inventory/system/backup_list.html', {'backups': backups})

@login_required
@permission_required('inventory.can_manage_backup')
def create_backup(request):
    """创建备份视图"""
    # 生成建议的备份名称
    now = datetime.now()
    suggested_name = f"backup_{now.strftime('%Y%m%d_%H%M%S')}"
    
    if request.method == 'POST':
        # 获取表单数据
        backup_name = request.POST.get('backup_name', '').strip()
        if not backup_name:
            backup_name = suggested_name
        
        # 验证备份名称
        if not re.match(r'^[a-zA-Z0-9_\-]+$', backup_name):
            messages.error(request, "备份名称只能包含字母、数字、下划线和连字符")
            return render(request, 'inventory/system/create_backup.html', {'suggested_name': suggested_name})
        
        # 检查备份是否已存在
        backup_dir = os.path.join(settings.BACKUP_ROOT, backup_name)
        if os.path.exists(backup_dir):
            messages.error(request, f"备份 {backup_name} 已存在")
            return render(request, 'inventory/system/create_backup.html', {'suggested_name': suggested_name})
        
        # 创建备份目录
        os.makedirs(backup_dir, exist_ok=True)
        
        try:
            # 备份数据库
            db_file = os.path.join(backup_dir, 'db.json')
            management.call_command('dumpdata', '--exclude', 'auth.permission', '--exclude', 'contenttypes', 
                                  '--exclude', 'sessions.session', '--indent', '4', 
                                  '--output', db_file)
            
            # 备份媒体文件
            backup_media = request.POST.get('backup_media') == 'on'
            if backup_media and os.path.exists(settings.MEDIA_ROOT):
                media_dir = os.path.join(backup_dir, 'media')
                os.makedirs(media_dir, exist_ok=True)
                
                # 复制媒体文件
                for item in os.listdir(settings.MEDIA_ROOT):
                    src_path = os.path.join(settings.MEDIA_ROOT, item)
                    dst_path = os.path.join(media_dir, item)
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dst_path)
                    else:
                        shutil.copy2(src_path, dst_path)
            
            # 备份描述
            backup_description = request.POST.get('backup_description', '').strip()
            
            # 保存备份信息
            backup_info = {
                'name': backup_name,
                'created_at': now.isoformat(),
                'created_by': request.user.username,
                'description': backup_description,
                'includes_media': backup_media,
            }
            
            backup_info_file = os.path.join(backup_dir, 'backup_info.json')
            with open(backup_info_file, 'w', encoding='utf-8') as f:
                json.dump(backup_info, f, indent=4, ensure_ascii=False)
            
            # 记录日志
            LogEntry.objects.create(
                user=request.user,
                action_type='BACKUP',
                object_id=backup_name,
                object_repr=f'备份: {backup_name}',
                change_message=f'创建了系统备份 {backup_name}' + (' 包含媒体文件' if backup_media else '')
            )
            
            messages.success(request, f"成功创建备份: {backup_name}")
            return redirect('backup_list')
            
        except Exception as e:
            # 备份失败，清理备份目录
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            
            messages.error(request, f"创建备份失败: {str(e)}")
            logger.error(f"创建备份失败: {str(e)}")
            return render(request, 'inventory/system/create_backup.html', {'suggested_name': suggested_name})
    
    return render(request, 'inventory/system/create_backup.html', {'suggested_name': suggested_name})

@login_required
@permission_required('inventory.can_manage_backup')
def restore_backup(request, backup_name):
    """恢复备份视图"""
    # 检查备份是否存在
    backup_dir = os.path.join(settings.BACKUP_ROOT, backup_name)
    if not os.path.exists(backup_dir):
        messages.error(request, f"备份 {backup_name} 不存在")
        return redirect('backup_list')
    
    # 获取备份信息
    backup_info_file = os.path.join(backup_dir, 'backup_info.json')
    try:
        with open(backup_info_file, 'r', encoding='utf-8') as f:
            backup_info = json.load(f)
    except Exception as e:
        messages.error(request, f"读取备份信息失败: {str(e)}")
        return redirect('backup_list')
    
    # 封装备份对象
    backup = {
        'name': backup_name,
        'created_at': datetime.fromisoformat(backup_info.get('created_at', '')),
        'created_by': backup_info.get('created_by', '未知'),
        'size': get_dir_size_display(backup_dir),
    }
    
    if request.method == 'POST':
        # 确认恢复
        if not request.POST.get('confirm_restore'):
            messages.error(request, "请确认恢复操作")
            return render(request, 'inventory/system/restore_backup.html', {'backup': backup})
        
        # 是否恢复媒体文件
        restore_media = request.POST.get('restore_media') == 'on'
        
        # 执行恢复
        try:
            # 创建临时目录
            temp_dir = os.path.join(settings.TEMP_DIR, f"restore_{backup_name}_{int(time.time())}")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 恢复数据库
            db_file = os.path.join(backup_dir, 'db.json')
            if not os.path.exists(db_file):
                messages.error(request, "备份中不存在数据库文件")
                return redirect('backup_list')
            
            # 执行数据库恢复
            management.call_command('flush', '--noinput')  # 清空当前数据库
            management.call_command('loaddata', db_file)  # 加载备份的数据
            
            # 恢复媒体文件
            if restore_media:
                media_backup = os.path.join(backup_dir, 'media')
                if os.path.exists(media_backup):
                    # 备份当前媒体文件
                    if os.path.exists(settings.MEDIA_ROOT):
                        current_media_backup = os.path.join(temp_dir, 'media_backup')
                        shutil.copytree(settings.MEDIA_ROOT, current_media_backup)
                    
                    # 删除当前媒体目录中的文件（保留目录结构）
                    for item in os.listdir(settings.MEDIA_ROOT):
                        item_path = os.path.join(settings.MEDIA_ROOT, item)
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                    
                    # 复制备份的媒体文件到媒体目录
                    for item in os.listdir(media_backup):
                        src_path = os.path.join(media_backup, item)
                        dst_path = os.path.join(settings.MEDIA_ROOT, item)
                        if os.path.isdir(src_path):
                            shutil.copytree(src_path, dst_path)
                        else:
                            shutil.copy2(src_path, dst_path)
            
            # 记录日志
            LogEntry.objects.create(
                user=request.user,
                action_type='RESTORE',
                object_id=backup_name,
                object_repr=f'备份: {backup_name}',
                change_message=f'从备份 {backup_name} 恢复了系统数据' + (' 和媒体文件' if restore_media else '')
            )
            
            messages.success(request, f"成功从备份 {backup_name} 恢复了系统数据" + (" 和媒体文件" if restore_media else ""))
            
            # 清理临时目录
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
            return redirect('dashboard')
            
        except Exception as e:
            # 恢复失败
            messages.error(request, f"恢复失败: {str(e)}")
            logger.error(f"恢复备份 {backup_name} 失败: {str(e)}")
            # 记录恢复失败日志
            LogEntry.objects.create(
                user=request.user,
                action_type='ERROR',
                object_id=backup_name,
                object_repr=f'备份: {backup_name}',
                change_message=f'恢复备份 {backup_name} 失败: {str(e)}'
            )
            return redirect('backup_list')
    
    return render(request, 'inventory/system/restore_backup.html', {'backup': backup})

@login_required
@permission_required('inventory.can_manage_backup')
def delete_backup(request, backup_name):
    """删除备份视图"""
    backup_dir = os.path.join(settings.BACKUP_ROOT, backup_name)
    if not os.path.exists(backup_dir):
        messages.error(request, f"备份 {backup_name} 不存在")
        return redirect('backup_list')
    
    try:
        # 删除备份目录
        shutil.rmtree(backup_dir)
        
        # 记录日志
        LogEntry.objects.create(
            user=request.user,
            action_type='DELETE',
            object_id=backup_name,
            object_repr=f'备份: {backup_name}',
            change_message=f'删除了系统备份 {backup_name}'
        )
        
        messages.success(request, f"成功删除备份: {backup_name}")
    except Exception as e:
        messages.error(request, f"删除备份失败: {str(e)}")
        logger.error(f"删除备份 {backup_name} 失败: {str(e)}")
    
    return redirect('backup_list')

@login_required
@permission_required('inventory.can_manage_backup')
def download_backup(request, backup_name):
    """下载备份视图"""
    backup_dir = os.path.join(settings.BACKUP_ROOT, backup_name)
    if not os.path.exists(backup_dir):
        messages.error(request, f"备份 {backup_name} 不存在")
        return redirect('backup_list')
    
    try:
        # 创建临时目录
        temp_dir = os.path.join(settings.TEMP_DIR, f"download_{backup_name}_{int(time.time())}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # 创建压缩文件
        zip_file_path = os.path.join(temp_dir, f"{backup_name}.zip")
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加备份信息
            for root, dirs, files in os.walk(backup_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, backup_dir))
        
        # 返回文件
        if os.path.exists(zip_file_path):
            with open(zip_file_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/zip')
                response['Content-Disposition'] = f'attachment; filename="{backup_name}.zip"'
                
                # 记录下载日志
                LogEntry.objects.create(
                    user=request.user,
                    action_type='DOWNLOAD',
                    object_id=backup_name,
                    object_repr=f'备份: {backup_name}',
                    change_message=f'下载了系统备份 {backup_name}'
                )
                
                # 清理临时目录
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
                    
                return response
        else:
            messages.error(request, "生成备份压缩文件失败")
            return redirect('backup_list')
            
    except Exception as e:
        messages.error(request, f"下载备份失败: {str(e)}")
        logger.error(f"下载备份 {backup_name} 失败: {str(e)}")
        return redirect('backup_list')

@login_required
@log_view_access('OTHER')
@permission_required('is_superuser')
def manual_backup(request):
    """
    手动备份API
    """
    if request.method == 'POST':
        try:
            backup_name = f"manual_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
            backup_path = BackupService.create_backup(backup_name=backup_name, user=request.user)
            return JsonResponse({
                'success': True,
                'backup_name': backup_name,
                'message': '备份创建成功'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'备份创建失败: {str(e)}'
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'message': '不支持的请求方法'
    }, status=405) 