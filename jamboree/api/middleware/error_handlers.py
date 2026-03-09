"""
Centralized error handling for JAMboreeLite API.

Provides consistent error responses and logging for API endpoints.
"""

import logging
from flask import jsonify
from typing import Tuple, Any


logger = logging.getLogger(__name__)


def handle_validation_error(message: str, field: str = None) -> Tuple[Any, int]:
    """
    Handle input validation errors.
    
    Args:
        message: Error message
        field: Optional field name that failed validation
        
    Returns:
        Tuple of (JSON response, status code)
    """
    logger.warning(f"Validation error: {message}" + (f" (field: {field})" if field else ""))
    
    response = {
        "ok": False,
        "error": "validation_error",
        "message": message
    }
    
    if field:
        response["field"] = field
    
    return jsonify(response), 400


def handle_not_found(resource: str, identifier: str = None) -> Tuple[Any, int]:
    """
    Handle resource not found errors.
    
    Args:
        resource: Resource type (e.g., "STB", "configuration")
        identifier: Optional resource identifier
        
    Returns:
        Tuple of (JSON response, status code)
    """
    message = f"{resource} not found"
    if identifier:
        message += f": {identifier}"
    
    logger.info(message)
    
    return jsonify({
        "ok": False,
        "error": "not_found",
        "message": message
    }), 404


def handle_server_error(error: Exception, message: str = None) -> Tuple[Any, int]:
    """
    Handle internal server errors.
    
    Args:
        error: Exception that occurred
        message: Optional custom message
        
    Returns:
        Tuple of (JSON response, status code)
    """
    logger.exception(f"Server error: {message or str(error)}")
    
    return jsonify({
        "ok": False,
        "error": "server_error",
        "message": message or "An internal error occurred"
    }), 500


def handle_auth_error(message: str = "Authentication required") -> Tuple[Any, int]:
    """
    Handle authentication/authorization errors.
    
    Args:
        message: Error message
        
    Returns:
        Tuple of (JSON response, status code)
    """
    logger.warning(f"Auth error: {message}")
    
    return jsonify({
        "ok": False,
        "error": "auth_error",
        "message": message
    }), 401


def handle_connection_error(target: str, details: str = None) -> Tuple[Any, int]:
    """
    Handle connection errors to external services.
    
    Args:
        target: Connection target (e.g., "STB", "serial port")
        details: Optional error details
        
    Returns:
        Tuple of (JSON response, status code)
    """
    message = f"Failed to connect to {target}"
    if details:
        message += f": {details}"
    
    logger.error(message)
    
    return jsonify({
        "ok": False,
        "error": "connection_error",
        "message": message
    }), 503


def success_response(data: dict = None, message: str = None) -> Tuple[Any, int]:
    """
    Generate a successful response.
    
    Args:
        data: Optional response data
        message: Optional success message
        
    Returns:
        Tuple of (JSON response, status code)
    """
    response = {"ok": True}
    
    if message:
        response["message"] = message
    
    if data:
        response.update(data)
    
    return jsonify(response), 200
